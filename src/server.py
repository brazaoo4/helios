import contextlib
import functools
import hashlib
import hmac
import json
import os
import re
import urllib.parse
import uuid
from typing import Annotated, AsyncGenerator, Literal, Optional

import anyio
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata
    from mcp.server.sse import TransportSecuritySettings
except ImportError:
    try:
        from fastmcp import FastMCP
        from fastmcp.utilities.func_metadata import FuncMetadata
    except ImportError:
        FastMCP = None
        FuncMetadata = None
    TransportSecuritySettings = None

# Offload sync FastMCP tools to worker thread via anyio.to_thread.run_sync during async MCP calls
if FuncMetadata is not None and not getattr(FuncMetadata, "_helios_offloaded", False):
    _orig_call_fn = FuncMetadata.call_fn_with_arg_validation

    async def _offloaded_call_fn(
        self,
        fn,
        fn_is_async: bool,
        arguments_to_validate,
        arguments_to_pass_directly,
    ):
        arguments_pre_parsed = self.pre_parse_json(arguments_to_validate)
        arguments_parsed_model = self.arg_model.model_validate(arguments_pre_parsed)
        arguments_parsed_dict = arguments_parsed_model.model_dump_one_level()
        arguments_parsed_dict |= arguments_to_pass_directly or {}

        if fn_is_async:
            return await fn(**arguments_parsed_dict)
        else:
            return await anyio.to_thread.run_sync(functools.partial(fn, **arguments_parsed_dict))

    FuncMetadata.call_fn_with_arg_validation = _offloaded_call_fn
    FuncMetadata._helios_offloaded = True

from src.config import (
    LOCKED_SECURITY_KEYS,
    MUTABLE_SETTINGS,
    get_allowed_origins,
    get_api_key,
    get_git_token,
    get_memory_data_dir,
    get_webhook_secret,
    get_webhook_url,
    resolve_setting_with_source,
    validate_setting_value,
)
from src.db import (
    delete_runtime_setting,
    deprecate_memory as db_deprecate_memory,
    flag_stale_by_files,
    get_connection,
    get_runtime_setting,
    get_scope_statistics,
    init_db,
    list_aliases,
    list_runtime_settings,
    migrate_scope,
    query_memories,
    remove_alias,
    resolve_scope,
    revalidate_memories as db_revalidate_memories,
    set_alias,
    set_runtime_setting,
    upsert_memory,
)
from src.exporter import (
    create_portable_archive,
    get_export_dir,
    sync_markdown_exports,
)
from src.onboarding import (
    generate_client_bundle,
    generate_setup_bash,
    generate_setup_markdown,
    generate_setup_powershell,
    resolve_server_base_url,
)
from src.seed import ingest_declarative_seed_files, is_db_empty, seed_if_empty
from src.webhooks import (
    disable_repo_webhooks,
    enable_repo_webhooks,
    list_repo_webhooks,
)

# 1. Initialize FastMCP Server Instance
HELIOS_INSTRUCTIONS = (
    "Helios is your centralized architectural memory across IDE and CLI agents. "
    "1. PRE-FLIGHT: Call recall_memories() at the start of any task using the current repo or folder name. "
    "2. STALE PROTOCOL: When a memory is marked [STALE], inspect the referenced anchor_files before acting. "
    "3. UPDATE RULE: If you modify an architecture choice, port, path, or bug fix, call save_memory() or deprecate_memory(). "
    "4. TOKEN BUDGET: Keep facts atomic (<= 25 words). Never store transient code snippets or secrets."
)
transport_security = (
    TransportSecuritySettings(enable_dns_rebinding_protection=False)
    if TransportSecuritySettings is not None
    else None
)
mcp = FastMCP("Helios", instructions=HELIOS_INSTRUCTIONS, transport_security=transport_security)
if hasattr(mcp, "settings") and hasattr(mcp.settings, "transport_security") and mcp.settings.transport_security:
    mcp.settings.transport_security.enable_dns_rebinding_protection = False

_ = mcp.streamable_http_app()
sse_app = mcp.sse_app()


class HybridMCPHandler:
    """
    Unified MCP ASGI dispatcher supporting both modern Streamable HTTP (POST /sse)
    and Server-Sent Events (GET /sse).
    """
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            method = scope.get("method", "GET")
            headers = dict(scope.get("headers", []))
            session_id_bytes = headers.get(b"mcp-session-id")

            # Check if this session is actively registered in Streamable HTTP
            has_active_streamable_session = False
            if session_id_bytes and hasattr(mcp, "session_manager"):
                try:
                    sid = session_id_bytes.decode("utf-8")
                    has_active_streamable_session = sid in getattr(mcp.session_manager, "_server_instances", {})
                except Exception:
                    has_active_streamable_session = False

            if hasattr(mcp, "session_manager"):
                # Always route POST and DELETE through Streamable HTTP session manager
                if method in ("POST", "DELETE"):
                    await mcp.session_manager.handle_request(scope, receive, send)
                    return
                # Route GET only if this is an active streamable session stream
                if method == "GET" and has_active_streamable_session:
                    await mcp.session_manager.handle_request(scope, receive, send)
                    return

            # For GET /sse (SSE transport): preserve token in emitted endpoint event
            if method == "GET":
                raw_qs = scope.get("query_string", b"").decode("utf-8", errors="ignore")
                qparams = urllib.parse.parse_qs(raw_qs)
                token_val = qparams.get("token", [None])[0]
                if token_val:
                    enc_token = urllib.parse.quote(token_val, safe="").encode("utf-8")

                    async def send_with_token(message):
                        if message.get("type") == "http.response.body":
                            body = message.get("body", b"")
                            if b"/messages/?session_id=" in body:
                                new_body = re.sub(
                                    rb"(/messages/\?session_id=[a-fA-F0-9]+)",
                                    rb"\1&token=" + enc_token,
                                    body,
                                )
                                message = {**message, "body": new_body}
                        await send(message)

                    await sse_app(scope, receive, send_with_token)
                    return

        # Fall through to SSE app for GET /sse without active streamable session
        await sse_app(scope, receive, send)


class StreamableMCPHandler:
    async def __call__(self, scope, receive, send):
        if hasattr(mcp, "session_manager"):
            await mcp.session_manager.handle_request(scope, receive, send)
        else:
            await sse_app(scope, receive, send)


hybrid_handler = HybridMCPHandler()
streamable_handler = StreamableMCPHandler()


COLD_START_ONBOARDING_NOTICE = (
    "[COLD START ONBOARDING] The Helios memory database currently contains zero active memories. "
    "1. Prompt the user for project context or inspect baseline project configuration files "
    "(e.g., README.md, package.json, compose.yaml, pyproject.toml) to seed initial architectural rules and facts "
    "using save_memory(). "
    "2. If this client environment has not installed the /remember skill or global memory directives yet, "
    "call get_client_setup_bundle() to retrieve and configure them."
)


# 2. FastMCP Tool Definitions
@mcp.tool()
def recall_memories(
    scope: Annotated[str, Field(default="global", description="Project, repository, or directory name (e.g., 'homelab', 'ticketera', 'global').")] = "global",
    query: Annotated[str, Field(default="", description="Natural language search query or keywords to match via FTS5 BM25.")] = "",
    category: Annotated[Literal["rule", "fact", "preference", "episodic", ""] | None, Field(default=None, description="Optional filter to retrieve only a specific category (e.g., 'rule' for coding guardrails).")] = None,
    status_filter: Annotated[Literal["all", "active", "stale"], Field(default="all", description="Filter by drift status: 'all' (default), 'active' only, or 'stale' only (to audit drifted memories).")] = "all",
    limit: Annotated[int, Field(default=8, ge=1, le=50, description="Maximum number of memories to return (clamped between 1 and 50).")] = 8,
    include_global: Annotated[bool, Field(default=True, description="Whether to include global guardrails and rules alongside scope-specific memories.")] = True,
) -> str:
    """
    Recall active memories from Helios using FTS5 BM25 search.
    """
    try:
        cat_filter = None if (category is None or category == "") else category
        memories = query_memories(
            raw_scope=scope,
            query=query,
            include_global=include_global,
            limit=limit,
            category=cat_filter,
            status_filter=status_filter,
        )
        if not memories:
            resolved = resolve_scope(scope)
            msg = f"No active memories found for scope '{resolved}'."
            if is_db_empty():
                return f"{COLD_START_ONBOARDING_NOTICE}\n\n{msg}"
            return msg

        lines = []
        for m in memories:
            subj = f"**[{m['subject']}]** " if m["subject"] else ""
            stale = f" `[STALE: {m['stale_reason']}]`" if m["status"] == "stale" else ""
            anchors = json.loads(m["anchor_files"] or "[]")
            anchor_str = f" _(anchors: `{', '.join(anchors)}`)_" if anchors else ""
            lines.append(
                f"- `#{m['id']}` ({m['scope']}/{m['category']}) {subj}{m['content']}{stale}{anchor_str}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Error recalling memories: {exc}"


@mcp.tool()
def save_memory(
    scope: Annotated[str, Field(description="Project, repository, or directory name (e.g., 'homelab', 'ticketera', 'global').")],
    category: Annotated[Literal["rule", "fact", "preference", "episodic"], Field(description="Memory classification: 'rule' (guardrails), 'fact' (architecture/ports), 'preference' (style), 'episodic' (temporary 14d notes).")],
    content: Annotated[str, Field(description="Atomic memory statement. STRICT LIMIT: MUST be <= 25 words. Omit filler words.")],
    subject: Annotated[str, Field(default="", description="Deterministic slot key (e.g., 'app-port', 'db-stack'). Saving with an existing (scope, subject) automatically supersedes the old fact.")] = "",
    anchor_files: Annotated[list[str] | None, Field(default=None, description="Repo-relative file paths (e.g., ['docker-compose.yml']). Git commits touching these files auto-flag this memory as [STALE].")] = None,
    replaces_id: Annotated[int | None, Field(default=None, description="Optional explicit memory ID to supersede.")] = None,
) -> str:
    """
    Save or update a memory in Helios (AUDN Write Gate).
    """
    try:
        res = upsert_memory(
            raw_scope=scope,
            category=category,
            content=content,
            subject=subject,
            anchor_files=anchor_files,
            replaces_id=replaces_id,
        )
        sync_markdown_exports()

        if res["action"] == "created":
            return f"Memory #{res['id']} created in scope '{res['scope']}'."
        elif res["action"] == "superseded":
            superseded = ", ".join(f"#{mid}" for mid in res["superseded_ids"])
            return f"Memory #{res['id']} created in scope '{res['scope']}', superseding {superseded}."
        elif "no-op" in res["action"]:
            return f"No-op: identical memory #{res['id']} already exists in scope '{res['scope']}'."
        return f"Memory #{res['id']} processed ({res['action']})."
    except Exception as exc:
        return f"Error saving memory: {exc}"


@mcp.tool()
def deprecate_memory(
    memory_id: Annotated[int, Field(description="Integer ID of the active or stale memory to retire/archive.")],
    reason: Annotated[str, Field(default="", description="Reason for deprecating the memory (e.g., 'replaced by microservice', 'obsolete config').")] = "",
) -> str:
    """
    Deprecate (archive) an active or stale memory that is obsolete.
    """
    try:
        res = db_deprecate_memory(memory_id, reason)
        sync_markdown_exports()
        return f"Memory #{res['id']} in scope '{res['scope']}' deprecated (archived)."
    except Exception as exc:
        return f"Error deprecating memory: {exc}"


@mcp.tool()
def recall_history(
    scope: Annotated[str, Field(default="global", description="Project, repository, or directory name to retrieve historical audit trail for.")] = "global",
    limit: Annotated[int, Field(default=10, ge=1, le=25, description="Maximum number of historical records to return (capped at 25).")] = 10,
) -> str:
    """
    Inspect previously superseded or archived memories for time-travel debugging
    and understanding configuration drift over time.
    """
    resolved = resolve_scope(scope)
    clamped_limit = max(1, min(limit, 25))
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, subject, content, status, superseded_by, valid_from, valid_to
                FROM memories
                WHERE scope = ? AND status IN ('superseded', 'archived')
                ORDER BY valid_to DESC
                LIMIT ?
                """,
                (resolved, clamped_limit),
            ).fetchall()

        if not rows:
            return f"No historical memories on record for scope '{resolved}'."

        lines = []
        for r in rows:
            subj = f"**[{r['subject']}]** " if r["subject"] else ""
            tag = f"superseded -> `#{r['superseded_by']}`" if r["superseded_by"] else "archived"
            lines.append(
                f"- `#{r['id']}` [{tag}] ({r['valid_from']} to {r['valid_to']}): {subj}{r['content']}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Error retrieving history: {exc}"


@mcp.tool()
def revalidate_memories(
    memory_ids: Annotated[list[int], Field(description="List of stale memory IDs to revalidate and mark back as 'active'.")],
) -> str:
    """
    Batch revalidate stale memories back to 'active' status after auditing anchor files.
    """
    try:
        res = db_revalidate_memories(memory_ids)
        revalidated = res["revalidated_ids"]
        not_stale = res["not_found_or_not_stale_ids"]
        if revalidated:
            sync_markdown_exports()

        if revalidated and not not_stale:
            return f"Revalidated {len(revalidated)} memories: {', '.join(f'#{i}' for i in revalidated)}."
        elif revalidated and not_stale:
            return (
                f"Revalidated {len(revalidated)} memories: {', '.join(f'#{i}' for i in revalidated)}. "
                f"Skipped {len(not_stale)} (not found or not stale): {', '.join(f'#{i}' for i in not_stale)}."
            )
        else:
            return f"No memories revalidated. Provided IDs were not found or not stale: {', '.join(f'#{i}' for i in not_stale)}."
    except Exception as exc:
        return f"Error revalidating memories: {exc}"


@mcp.tool()
def export_bundle() -> str:
    """
    Generate a complete, portable archive snapshot (helios_portable_bundle.tar.gz)
    using the SQLite Online Backup API, bundling the DB and all Markdown exports.
    """
    try:
        archive_path = create_portable_archive()
        size_kb = round(os.path.getsize(archive_path) / 1024, 2)
        return f"Snapshot created: {archive_path} ({size_kb} KB)."
    except Exception as exc:
        return f"Error generating export bundle: {exc}"


@mcp.tool()
def manage_scope_alias(
    alias: Annotated[str, Field(default="", description="Source alias or folder name (e.g., 'ticket-tracker').")] = "",
    canonical_scope: Annotated[str, Field(default="", description="Target canonical scope name (e.g., 'ticketera').")] = "",
    action: Annotated[Literal["set", "remove", "list", "rename"], Field(default="set", description="Action to perform: 'set' (map alias), 'remove' (delete alias), 'list' (show all), or 'rename' (migrate all memories to new scope and register alias).")] = "set",
) -> str:
    """
    Manage project and folder aliases mapping to canonical memory scopes.
    - action='set': Maps alias -> canonical_scope (e.g. 'frontend-v2' -> 'web').
    - action='remove': Deletes an existing alias mapping.
    - action='list': Returns all current alias-to-scope mappings.
    - action='rename': Migrates all memories from alias to canonical_scope and registers alias.
    """
    try:
        act = (action or "").strip().lower()
        if act == "set":
            set_alias(alias, canonical_scope)
            mappings = list_aliases()
            clean_alias = alias.strip().replace("\\", "/").rstrip("/").split("/")[-1].lower()
            if clean_alias.endswith(".git"):
                clean_alias = clean_alias[:-4]
            resolved_target = mappings.get(clean_alias, canonical_scope.strip().lower())
            return f"Alias '{clean_alias}' mapped to canonical scope '{resolved_target}'."
        elif act in ("remove", "delete"):
            removed = remove_alias(alias)
            if removed:
                return f"Alias '{alias.strip().lower()}' removed."
            return f"Alias '{alias.strip().lower()}' not found."
        elif act == "list":
            mappings = list_aliases()
            scope_stats = get_scope_statistics()
            lines = ["### Configured Scope Aliases"]
            if not mappings:
                lines.append("No scope aliases configured.")
            else:
                for k, v in mappings.items():
                    lines.append(f"- `{k}` -> `{v}`")

            lines.append("")
            lines.append("### Active Scopes in Memory")
            if not scope_stats:
                lines.append("No scopes found in memory.")
            else:
                for s in scope_stats:
                    alias_note = f" <- aliases: {', '.join(f'`{a}`' for a in s['aliases'])}" if s["aliases"] else ""
                    lines.append(f"- `{s['scope']}` ({s['active_count']} active, {s['stale_count']} stale){alias_note}")

            return "\n".join(lines)
        elif act == "rename":
            res = migrate_scope(from_scope=alias, to_scope=canonical_scope, register_alias=True)
            sync_markdown_exports()
            return (
                f"Scope '{res['from_scope']}' migrated to '{res['to_scope']}' "
                f"({res['migrated_count']} memories moved). Alias registered."
            )
        else:
            return f"Invalid action '{action}'. Must be 'set', 'remove', 'list', or 'rename'."
    except Exception as exc:
        return f"Error managing scope alias: {exc}"


@mcp.tool()
def manage_git_webhooks(
    action: Annotated[
        Literal["list", "enable", "disable"],
        Field(description="Action to perform: 'list' (display repos and drift hook status), 'enable' (attach drift webhook), or 'disable' (remove drift webhook).")
    ] = "list",
    repos: Annotated[
        list[str] | None,
        Field(default=None, description="List of repository names (e.g. ['braz/helios', 'braz/homelab']) to enable or disable.")
    ] = None,
    include_forks: Annotated[
        bool,
        Field(default=False, description="Whether to include forked repositories when listing.")
    ] = False,
) -> str:
    """
    Manage Git repository push drift detection webhooks across Forgejo, Gitea, GitHub, or GitLab.
    """
    token = get_git_token()
    webhook_url = get_webhook_url()

    if not token or not webhook_url:
        missing = []
        if not token:
            missing.append("HELIOS_GIT_TOKEN")
        if not webhook_url:
            missing.append("HELIOS_WEBHOOK_URL")

        sample_url = webhook_url or f"{resolve_server_base_url()}/webhook/git"
        return (
            f"Git webhook management is not configured on this server (missing: {', '.join(missing)}).\n\n"
            "### Manual Configuration (Git Web UI):\n"
            f"1. Open repository settings -> Webhooks -> Add Webhook.\n"
            f"2. Payload URL: `{sample_url}`\n"
            "3. Content type: `application/json`\n"
            f"4. Secret: Set your `HELIOS_WEBHOOK_SECRET`.\n"
            "5. Trigger: Push events.\n\n"
            "### Conversational Automation Configuration:\n"
            "Configure the following in your Helios `.env` and restart Helios:\n"
            "```bash\n"
            "HELIOS_GIT_PROVIDER=forgejo  # or gitea, github, gitlab\n"
            "HELIOS_GIT_API_URL=https://git.example.com\n"
            "HELIOS_GIT_TOKEN=your_personal_access_token\n"
            f"HELIOS_WEBHOOK_URL={sample_url}\n"
            "```"
        )

    try:
        act = (action or "list").strip().lower()
        if act == "list":
            candidates = list_repo_webhooks(include_forks=include_forks)
            if not candidates:
                return "No eligible repositories found owned by the authenticated Git user."

            lines = ["### Git Repository Drift Webhook Status\n"]
            for c in candidates:
                mark = "[x]" if c["enabled"] else "[ ]"
                status_str = "drift webhook active" if c["enabled"] else "drift webhook not configured"
                scope_str = f", matched Helios scope: `{c['matched_scope']}`" if c.get("matched_scope") else ""
                fork_str = " (fork)" if c.get("is_fork") else ""
                lines.append(f"- {mark} `{c['repo']}`{fork_str} ({status_str}{scope_str})")

            lines.append(
                "\n> **Agent Instruction**: Show this checklist to the user and ask which repositories "
                "they want to enable before calling `manage_git_webhooks(action='enable', repos=[...])`."
            )
            return "\n".join(lines)

        elif act == "enable":
            if not repos:
                return "Error: Please specify one or more repository names to enable webhooks on (e.g., repos=['owner/repo'])."
            res = enable_repo_webhooks(repos=repos)
            parts = []
            if res["enabled"]:
                parts.append(f"Successfully enabled drift webhooks on: {', '.join(f'`{r}`' for r in res['enabled'])}.")
            if res["already_enabled"]:
                parts.append(f"Already enabled: {', '.join(f'`{r}`' for r in res['already_enabled'])}.")
            if res["failed"]:
                err_strs = [f"`{f['repo']}`: {f['error']}" for f in res["failed"]]
                parts.append(f"Failed to enable on: {'; '.join(err_strs)}.")
            return "\n".join(parts) if parts else "No changes made."

        elif act == "disable":
            if not repos:
                return "Error: Please specify one or more repository names to disable webhooks on (e.g., repos=['owner/repo'])."
            res = disable_repo_webhooks(repos=repos)
            parts = []
            if res["disabled"]:
                parts.append(f"Successfully disabled drift webhooks on: {', '.join(f'`{r}`' for r in res['disabled'])}.")
            if res["not_found"]:
                parts.append(f"No active Helios webhook found on: {', '.join(f'`{r}`' for r in res['not_found'])}.")
            if res["failed"]:
                err_strs = [f"`{f['repo']}`: {f['error']}" for f in res["failed"]]
                parts.append(f"Failed to disable on: {'; '.join(err_strs)}.")
            return "\n".join(parts) if parts else "No changes made."

        else:
            return f"Invalid action '{action}'. Must be 'list', 'enable', or 'disable'."
    except Exception as exc:
        return f"Error managing git webhooks: {exc}"


@mcp.tool()
def manage_server_config(
    action: Annotated[
        Literal["list", "set", "reset"],
        Field(description="Action: 'list' (show all configurable settings, active values, and source: db/env/default), 'set' (override a setting live in SQLite without restarting), or 'reset' (delete SQLite override and revert to env/default).")
    ] = "list",
    key: Annotated[
        str,
        Field(default="", description="Setting name to modify or reset (e.g., 'HELIOS_WORD_LIMIT', 'HELIOS_EPISODIC_TTL_DAYS', 'HELIOS_GIT_PROVIDER', 'HELIOS_GIT_API_URL', 'HELIOS_GIT_TOKEN', 'HELIOS_WEBHOOK_URL', 'HELIOS_PUBLIC_URL').")
    ] = "",
    value: Annotated[
        str,
        Field(default="", description="New value to apply when action='set'.")
    ] = "",
) -> str:
    """
    Manage live Day-2 Helios server configuration settings in SQLite without restarting the container.
    """
    act = (action or "list").strip().lower()

    if act == "list":
        lines = [
            "### Live Server Configuration (Day-2 Management)",
            "",
            "| Setting | Active Value | Source | Description |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for k in sorted(MUTABLE_SETTINGS.keys()):
            val, src = resolve_setting_with_source(k)
            meta = MUTABLE_SETTINGS[k]
            if meta.get("sensitive"):
                display_val = "•••••••• (configured)" if val else "(unset)"
            else:
                display_val = f"`{val}`" if (val != "" and val is not None) else "(unset)"
            lines.append(f"| `{k}` | {display_val} | `{src}` | {meta['description']} |")

        api_key_status = "enabled (configured via env)" if get_api_key() else "disabled (open mode)"
        hook_secret_status = "enabled (configured via env)" if get_webhook_secret() else "disabled"
        origins_str = ", ".join(get_allowed_origins())

        lines.extend([
            "",
            "### Security Environment Status (Read-Only via env)",
            f"- `HELIOS_API_KEY`: {api_key_status}",
            f"- `HELIOS_WEBHOOK_SECRET`: {hook_secret_status}",
            f"- `HELIOS_ALLOWED_ORIGINS`: `{origins_str}`",
            f"- `MEMORY_DATA_DIR`: `{get_memory_data_dir()}`",
        ])
        return "\n".join(lines)

    elif act == "set":
        if not key.strip():
            return "Error: 'key' is required when action='set'."
        k = key.strip().upper()
        if k in LOCKED_SECURITY_KEYS:
            return (
                f"Security violation: '{k}' is a locked security setting and cannot be modified at runtime. "
                "It must be configured strictly via server environment variables."
            )
        if k not in MUTABLE_SETTINGS:
            return f"Error: Unknown setting '{k}'. Configurable settings are: {', '.join(sorted(MUTABLE_SETTINGS.keys()))}."

        try:
            valid_val = validate_setting_value(k, value)
        except ValueError as exc:
            return f"Validation error for '{k}': {exc}"

        set_runtime_setting(k, str(valid_val) if valid_val is not None else "")
        display_val = "•••••••• (configured)" if MUTABLE_SETTINGS[k].get("sensitive") and valid_val else valid_val
        return f"Setting '{k}' updated live in SQLite to '{display_val}'. Effective immediately without restarting."

    elif act == "reset":
        if not key.strip():
            return "Error: 'key' is required when action='reset'."
        k = key.strip().upper()
        if k in LOCKED_SECURITY_KEYS:
            return f"Security violation: '{k}' is a locked security setting and cannot be modified at runtime."
        if k not in MUTABLE_SETTINGS:
            return f"Error: Unknown setting '{k}'. Configurable settings are: {', '.join(sorted(MUTABLE_SETTINGS.keys()))}."

        deleted = delete_runtime_setting(k)
        val, src = resolve_setting_with_source(k)
        meta = MUTABLE_SETTINGS[k]
        display_val = "•••••••• (configured)" if meta.get("sensitive") and val else (val if val is not None else "(unset)")
        if deleted:
            return f"Setting '{k}' reset in SQLite override. Active value reverted to {src} ('{display_val}')."
        return f"Setting '{k}' had no SQLite override. Current value is '{display_val}' from {src}."

    else:
        return f"Invalid action '{action}'. Must be 'list', 'set', or 'reset'."


@mcp.tool()
def get_client_setup_bundle(
    client: Annotated[
        Literal["antigravity", "cursor", "claude-desktop", "claude-code", "all"],
        Field(description="Target client environment to configure.")
    ] = "all",
    os_platform: Annotated[
        Literal["windows", "linux", "macos", "auto"],
        Field(description="Target operating system for config file paths.")
    ] = "auto",
    instance_role: Annotated[
        Literal["workstation", "server-cli"],
        Field(description="Role of this machine ('workstation' for IDE/laptop or 'server-cli' for headless host with strict log-truncation rules).")
    ] = "workstation",
    action: Annotated[
        Literal["install_or_update", "switch_role", "uninstall"],
        Field(description="Lifecycle action: 'install_or_update' (idempotently set or refresh client config and directive blocks), 'switch_role' (change machine role between 'workstation' and 'server-cli'), or 'uninstall' (instructions to cleanly remove Helios from MCP config, strip the HELIOS marker block, and remove the /remember skill).")
    ] = "install_or_update",
) -> str:
    """
    Retrieve client configuration snippets, global directives (GEMINI.md), and the /remember skill definition.
    """
    base_url = resolve_server_base_url()
    return generate_client_bundle(
        client=client,
        os_platform=os_platform,
        instance_role=instance_role,
        base_url=base_url,
        action=action,
    )


# 3. Zero-Trust Authentication Helpers & Middleware
def is_request_authenticated(request: Request) -> bool:
    """
    Validate request credentials against HELIOS_API_KEY using constant-time hmac.compare_digest.
    Returns True if HELIOS_API_KEY is unset (open local/mesh mode) or if credentials match:
      1. Header: `Authorization: Bearer <key>`
      2. Query Parameter: `?token=<key>`
    """
    api_key = get_api_key()
    if not api_key:
        return True

    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        candidate_bearer = auth_header[7:].strip()
        if candidate_bearer and hmac.compare_digest(candidate_bearer.encode("utf-8"), api_key.encode("utf-8")):
            return True

    query_token = request.query_params.get("token", "").strip()
    if query_token and hmac.compare_digest(query_token.encode("utf-8"), api_key.encode("utf-8")):
        return True

    # Validate active authenticated SSE session on POST to /messages
    if request.method == "POST" and request.url.path.rstrip("/").endswith("/messages"):
        raw_sid = request.query_params.get("session_id", "").strip()
        if raw_sid:
            try:
                sid = uuid.UUID(hex=raw_sid)
                for route in getattr(sse_app, "routes", []):
                    transport = getattr(getattr(route, "app", None), "__self__", None)
                    writers = getattr(transport, "_read_stream_writers", None)
                    if isinstance(writers, dict) and sid in writers:
                        return True
            except Exception:
                pass

    return False


class AuthGateMiddleware(BaseHTTPMiddleware):
    """
    Zero-Trust Security Middleware:
    - If HELIOS_API_KEY is unset, passes all requests (open local/mesh mode).
    - If set, enforces constant-time authentication via Authorization: Bearer <key> or ?token=<key>.
    - Exempts POST /webhook/* (and /hooks/git-commit), GET /health, and GET /setup.
    """
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if request.method == "GET" and (path == "/health" or path in ("/setup", "/setup.ps1", "/setup.sh")):
            return await call_next(request)

        if request.method == "POST" and (path.startswith("/webhook/") or path == "/hooks/git-commit"):
            return await call_next(request)

        if not is_request_authenticated(request):
            return JSONResponse(
                {"status": "error", "message": "Unauthorized: missing or invalid API key."},
                status_code=401,
            )

        return await call_next(request)


# 4. Application Lifespan Context
@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
    init_db()
    ingest_declarative_seed_files()
    if os.getenv("HELIOS_AUTO_SEED", "false").lower() in ("1", "true", "yes"):
        seed_if_empty()
    sync_markdown_exports()
    if hasattr(mcp, "_session_manager") and mcp._session_manager is not None:
        if getattr(mcp._session_manager, "_has_started", False):
            mcp._session_manager = None
            _ = mcp.streamable_http_app()
    if hasattr(mcp, "session_manager") and mcp.session_manager:
        async with mcp.session_manager.run():
            yield
    else:
        yield


# 5. HTTP Endpoints & Universal Git Webhook Adapter
def _query_health_status() -> tuple[str, int]:
    with get_connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        active_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status = 'active' AND valid_to IS NULL;"
        ).fetchone()[0]
    return journal_mode, active_count


async def health_check(request: Request) -> JSONResponse:
    try:
        journal_mode, active_count = await anyio.to_thread.run_sync(_query_health_status)

        if not is_request_authenticated(request):
            return JSONResponse(
                {
                    "status": "healthy",
                    "service": "helios",
                },
                status_code=200,
            )

        return JSONResponse(
            {
                "status": "healthy",
                "service": "helios",
                "database": {
                    "connected": True,
                    "journal_mode": journal_mode,
                    "active_memories": active_count,
                },
            },
            status_code=200,
        )
    except Exception as exc:
        if not is_request_authenticated(request):
            return JSONResponse(
                {
                    "status": "unhealthy",
                    "service": "helios",
                },
                status_code=503,
            )
        return JSONResponse(
            {
                "status": "unhealthy",
                "service": "helios",
                "error": str(exc),
            },
            status_code=503,
        )


async def export_bundle_download(request: Request) -> Response:
    """
    HTTP GET endpoint to download the latest helios_portable_bundle.tar.gz.
    Generates a fresh snapshot on demand in a worker thread.
    """
    try:
        archive_path = await anyio.to_thread.run_sync(create_portable_archive)
        return FileResponse(
            path=archive_path,
            filename="helios_portable_bundle.tar.gz",
            media_type="application/gzip",
        )
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"Failed to generate bundle: {exc}"},
            status_code=500,
        )


def _scan_markdown_exports() -> list[dict]:
    export_dir = get_export_dir()
    if not export_dir.exists():
        return []

    files = []
    for file_path in sorted(export_dir.glob("*.md")):
        files.append({
            "scope": file_path.stem,
            "filename": file_path.name,
            "size_bytes": file_path.stat().st_size,
        })
    return files


async def list_markdown_exports(request: Request) -> JSONResponse:
    """
    HTTP GET endpoint listing all generated markdown files and sizes.
    """
    files = await anyio.to_thread.run_sync(_scan_markdown_exports)
    return JSONResponse({"exports": files}, status_code=200)


def verify_forgejo_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header:
        return False
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    sig_clean = signature_header.strip()
    if sig_clean.startswith("sha256="):
        sig_clean = sig_clean[7:].strip()
    return hmac.compare_digest(expected_signature, sig_clean)


def verify_github_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header:
        return False
    sig_clean = signature_header.strip()
    if not sig_clean.startswith("sha256="):
        return False
    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, sig_clean)


def _detect_webhook_provider_and_verify(
    request: Request,
    raw_body: bytes,
    webhook_secret: str | None,
) -> tuple[str, bool]:
    """
    Auto-detect Git provider from incoming headers and verify webhook authenticity.
    Returns (provider_name, is_authenticated).
    """
    headers = request.headers
    gh_sig = headers.get("X-Hub-Signature-256", "")
    forgejo_sig = headers.get("X-Forgejo-Signature") or headers.get("X-Gitea-Signature") or ""
    gitlab_token = headers.get("X-Gitlab-Token", "")
    auth_header = headers.get("Authorization", "").strip()

    # Determine provider
    if "X-Gitlab-Event" in headers or "X-Gitlab-Token" in headers:
        provider = "gitlab"
    elif "X-Forgejo-Event" in headers or "X-Forgejo-Signature" in headers or "X-Gitea-Event" in headers or "X-Gitea-Signature" in headers:
        provider = "forgejo"
    elif "X-GitHub-Event" in headers or "X-Hub-Signature-256" in headers:
        provider = "github"
    else:
        provider = "generic"

    if not webhook_secret:
        return provider, True

    # 1. GitHub verification (sha256=<hex>)
    if gh_sig and verify_github_signature(raw_body, gh_sig, webhook_secret):
        return provider, True

    # 2. Forgejo / Gitea verification (<hex> or sha256=<hex>)
    if forgejo_sig and verify_forgejo_signature(raw_body, forgejo_sig, webhook_secret):
        return provider, True

    # 3. GitLab token verification (constant-time match on X-Gitlab-Token)
    if gitlab_token and hmac.compare_digest(gitlab_token.strip().encode("utf-8"), webhook_secret.encode("utf-8")):
        return provider, True

    # 4. Generic Authorization: Bearer <secret>
    if auth_header and hmac.compare_digest(auth_header.encode("utf-8"), f"Bearer {webhook_secret}".encode("utf-8")):
        return provider, True

    return provider, False


def _is_push_event(request: Request, payload: dict | None = None) -> tuple[bool, str]:
    """
    Normalize event headers across GitHub, Forgejo/Gitea, and GitLab to check for push events.
    Returns (is_push, raw_event_name).
    """
    headers = request.headers
    raw_event = (
        headers.get("X-GitHub-Event")
        or headers.get("X-Forgejo-Event")
        or headers.get("X-Gitea-Event")
        or headers.get("X-Gitlab-Event")
        or ""
    ).strip()

    if not raw_event:
        if isinstance(payload, dict) and payload.get("object_kind"):
            raw_event = str(payload["object_kind"]).strip()
        else:
            raw_event = "push"

    normalized = raw_event.lower()
    is_push = normalized in ("push", "push hook", "tag_push", "tag push hook")
    return is_push, raw_event


def _process_webhook_drift(repo_name: str, changed_files: list[str], commit_sha: str) -> int:
    flagged_count = flag_stale_by_files(
        repo_name=repo_name,
        modified_files=changed_files,
        commit_sha=commit_sha,
    )
    if flagged_count > 0:
        sync_markdown_exports()
    return flagged_count


MAX_WEBHOOK_BYTES = 1_048_576


async def _read_bounded_body(request: Request, max_bytes: int = MAX_WEBHOOK_BYTES) -> bytes | None:
    """Read incoming request body with strict size limit enforcement."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return None
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def git_webhook(request: Request) -> JSONResponse:
    """
    Universal Git Webhook Adapter (`POST /webhook/git` & `POST /webhook/forgejo`).
    Supports GitHub, Forgejo/Gitea, and GitLab push events.
    """
    raw_body = await _read_bounded_body(request, max_bytes=MAX_WEBHOOK_BYTES)
    if raw_body is None:
        return JSONResponse(
            {"status": "error", "message": "Payload exceeds 1MB limit."},
            status_code=413,
        )

    webhook_secret = get_webhook_secret()
    require_secret = os.getenv("HELIOS_REQUIRE_WEBHOOK_SECRET", "false").lower() in ("1", "true", "yes")

    if require_secret and not webhook_secret:
        return JSONResponse(
            {"status": "error", "message": "HELIOS_WEBHOOK_SECRET is not configured on the server."},
            status_code=503,
        )

    provider, is_valid = _detect_webhook_provider_and_verify(request, raw_body, webhook_secret)
    if not is_valid:
        return JSONResponse(
            {"status": "error", "message": "Invalid or missing webhook signature."},
            status_code=401,
        )

    # Check event header before parsing body if header is present
    is_push_hdr, event_name_hdr = _is_push_event(request)
    if not is_push_hdr:
        return JSONResponse(
            {"status": "ignored", "provider": provider, "message": f"Event '{event_name_hdr}' ignored (only 'push' triggers drift detection)."},
            status_code=200,
        )

    if not raw_body or not raw_body.strip():
        return JSONResponse({"status": "error", "message": "Empty webhook payload."}, status_code=400)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return JSONResponse({"status": "error", "message": "Malformed JSON payload."}, status_code=400)

    if not isinstance(payload, dict) or not payload:
        return JSONResponse({"status": "error", "message": "Empty or invalid JSON payload."}, status_code=400)

    is_push, event_name = _is_push_event(request, payload)
    if not is_push:
        return JSONResponse(
            {"status": "ignored", "provider": provider, "message": f"Event '{event_name}' ignored (only 'push' triggers drift detection)."},
            status_code=200,
        )

    repo_info = payload.get("repository") or {}
    project_info = payload.get("project") or {}
    repo_name = ""
    if isinstance(repo_info, dict):
        repo_name = repo_info.get("name") or repo_info.get("full_name") or repo_info.get("path_with_namespace") or ""
    if not repo_name and isinstance(project_info, dict):
        repo_name = project_info.get("name") or project_info.get("path_with_namespace") or ""

    if not repo_name:
        return JSONResponse({"status": "error", "message": "Missing repository name in payload."}, status_code=400)

    changed_files: set[str] = set()
    raw_commits = payload.get("commits")
    commits = raw_commits if isinstance(raw_commits, list) else []

    for commit in commits:
        if not isinstance(commit, dict):
            continue
        for key in ("added", "modified", "removed"):
            file_list = commit.get(key)
            if isinstance(file_list, list):
                changed_files.update(f for f in file_list if isinstance(f, str))

    commit_sha = payload.get("after") or payload.get("checkout_sha") or ""
    if not commit_sha or commit_sha == "0000000000000000000000000000000000000000":
        head_commit = payload.get("head_commit")
        if isinstance(head_commit, dict) and head_commit.get("id"):
            commit_sha = str(head_commit["id"])
        elif commits and isinstance(commits[-1], dict):
            commit_sha = str(commits[-1].get("id", "latest"))
        else:
            commit_sha = "latest"

    flagged_count = await anyio.to_thread.run_sync(
        _process_webhook_drift,
        repo_name,
        list(changed_files),
        commit_sha,
    )

    return JSONResponse(
        {
            "status": "processed",
            "provider": provider,
            "repository": repo_name,
            "commits_evaluated": len(commits),
            "files_evaluated": len(changed_files),
            "memories_flagged_stale": flagged_count,
        },
        status_code=200,
    )


# Backwards-compatible alias for forgejo_webhook
forgejo_webhook = git_webhook


async def setup_instructions(request: Request) -> Response:
    """
    HTTP GET /setup endpoint returning self-contained setup instructions
    for AI agents (curl -fsSL https://<host>/setup).
    """
    headers_dict = dict(request.headers)
    base_url = resolve_server_base_url(headers_dict)
    has_auth = get_api_key() is not None
    query_token = request.query_params.get("token")
    content = generate_setup_markdown(base_url=base_url, has_auth=has_auth, query_token=query_token)
    return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")


async def setup_powershell_script(request: Request) -> Response:
    """
    HTTP GET /setup.ps1 endpoint returning an automated 1-liner PowerShell setup script.
    Usage: irm https://<host>/setup.ps1 | iex
    """
    headers_dict = dict(request.headers)
    base_url = resolve_server_base_url(headers_dict)
    query_token = request.query_params.get("token")
    script = generate_setup_powershell(base_url=base_url, query_token=query_token)
    return PlainTextResponse(script, media_type="text/plain; charset=utf-8")


async def setup_bash_script(request: Request) -> Response:
    """
    HTTP GET /setup.sh endpoint returning an automated 1-liner Bash setup script.
    Usage: curl -fsSL https://<host>/setup.sh | bash
    """
    headers_dict = dict(request.headers)
    base_url = resolve_server_base_url(headers_dict)
    query_token = request.query_params.get("token")
    script = generate_setup_bash(base_url=base_url, query_token=query_token)
    return PlainTextResponse(script, media_type="text/plain; charset=utf-8")


# 6. Assemble Starlette ASGI Application
starlette_routes = [
    Route("/health", health_check, methods=["GET"]),
    Route("/setup", setup_instructions, methods=["GET"]),
    Route("/setup.ps1", setup_powershell_script, methods=["GET"]),
    Route("/setup.sh", setup_bash_script, methods=["GET"]),
    Route("/export/bundle", export_bundle_download, methods=["GET"]),
    Route("/export/markdown", list_markdown_exports, methods=["GET"]),
    Route("/webhook/git", git_webhook, methods=["POST"]),
    Route("/webhook/forgejo", forgejo_webhook, methods=["POST"]),
    Route("/hooks/git-commit", git_webhook, methods=["POST"]),
    Route("/sse", endpoint=hybrid_handler),
    Route("/mcp", endpoint=streamable_handler or hybrid_handler),
    Mount("/", app=sse_app),
]

app = Starlette(
    routes=starlette_routes,
    lifespan=lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=get_allowed_origins(),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        ),
        Middleware(AuthGateMiddleware),
    ],
)
