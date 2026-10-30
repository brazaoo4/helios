"""Core FastMCP memory query and lifecycle tools."""

import json
from typing import Annotated, Literal

from pydantic import Field

from src import __version__
from src.db import (
    deprecate_memory as db_deprecate_memory,
)
from src.db import (
    get_connection,
    query_memories,
    resolve_scope,
    upsert_memory,
)
from src.db import (
    revalidate_memories as db_revalidate_memories,
)
from src.exporter import sync_markdown_exports
from src.seed import is_db_empty
from src.tools.base import ToolAnnotations, mcp

COLD_START_ONBOARDING_NOTICE = (
    "[COLD START ONBOARDING] The Helios memory database currently contains zero active memories. "
    "1. Prompt the user for project context or inspect baseline project configuration files "
    "(e.g., README.md, package.json, compose.yaml, pyproject.toml) to seed initial architectural rules and facts "
    "using save_memory(). "
    "2. If this client environment has not installed the /remember skill or global memory directives yet, "
    "call get_client_setup_bundle() to retrieve and configure them."
)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def recall_memories(
    scope: Annotated[
        str,
        Field(
            default="global",
            description="Project, repository, or directory name (e.g., 'homelab', 'ticketera', 'global').",
        ),
    ] = "global",
    query: Annotated[
        str,
        Field(
            default="",
            description="Natural language search query or keywords to match via FTS5 BM25.",
        ),
    ] = "",
    category: Annotated[
        Literal["rule", "fact", "preference", "episodic", ""] | None,
        Field(
            default=None,
            description="Optional filter to retrieve only a specific category (e.g., 'rule' for coding guardrails).",
        ),
    ] = None,
    status_filter: Annotated[
        Literal["all", "active", "stale"],
        Field(
            default="all",
            description="Filter by drift status: 'all' (default), 'active' only, or 'stale' only (to audit drifted memories).",
        ),
    ] = "all",
    limit: Annotated[
        int,
        Field(
            default=8,
            ge=1,
            le=50,
            description="Maximum number of memories to return (clamped between 1 and 50).",
        ),
    ] = 8,
    include_global: Annotated[
        bool,
        Field(
            default=True,
            description="Whether to include global guardrails and rules alongside scope-specific memories.",
        ),
    ] = True,
    directive_version: Annotated[
        str,
        Field(
            default="",
            description="Client directive version from the local <!-- HELIOS:START --> header (e.g., '1.5.0'). Leave empty if unversioned/legacy.",
        ),
    ] = "",
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
        drift_banner = ""
        if status_filter == "all" and cat_filter is None and not is_db_empty():
            clean_client_ver = directive_version.strip().lstrip("v")
            clean_server_ver = __version__.strip().lstrip("v")
            if clean_client_ver != clean_server_ver:
                ver_label = f"v{clean_client_ver}" if clean_client_ver else "unversioned/legacy"
                drift_banner = (
                    f"\n\n> [CLIENT DIRECTIVE DRIFT: Local Helios directives ({ver_label}) are out of sync with "
                    f"Helios Server v{clean_server_ver}. Call get_client_setup_bundle(action='install_or_update') "
                    "to update your local directive file. Do NOT call save_memory for local client config updates.]"
                )

        if not memories:
            resolved = resolve_scope(scope)
            msg = f"No active memories found for scope '{resolved}'."
            if is_db_empty():
                return f"{COLD_START_ONBOARDING_NOTICE}\n\n{msg}"
            return f"{msg}{drift_banner}"

        lines = []
        for m in memories:
            subj = f"**[{m['subject']}]** " if m["subject"] else ""
            stale = f" `[STALE: {m['stale_reason']}]`" if m["status"] == "stale" else ""
            anchors = json.loads(m["anchor_files"] or "[]")
            anchor_str = f" _(anchors: `{', '.join(anchors)}`)_" if anchors else ""
            lines.append(
                f"- `#{m['id']}` ({m['scope']}/{m['category']}) {subj}{m['content']}{stale}{anchor_str}"
            )
        return "\n".join(lines) + drift_banner
    except Exception as exc:
        return f"Error recalling memories: {exc}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def save_memory(
    scope: Annotated[
        str,
        Field(
            description="Project, repository, or directory name (e.g., 'homelab', 'ticketera', 'global')."
        ),
    ],
    category: Annotated[
        Literal["rule", "fact", "preference", "episodic"],
        Field(
            description="Memory classification: 'rule' (guardrails), 'fact' (architecture/ports), 'preference' (style), 'episodic' (temporary 14d notes)."
        ),
    ],
    content: Annotated[
        str,
        Field(
            description="Atomic memory statement. STRICT LIMIT: MUST be <= 25 words. Omit filler words."
        ),
    ],
    subject: Annotated[
        str,
        Field(
            default="",
            description="Deterministic slot key (e.g., 'app-port', 'db-stack'). Saving with an existing (scope, subject) automatically supersedes the old fact.",
        ),
    ] = "",
    anchor_files: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="Repo-relative file paths (e.g., ['docker-compose.yml']). Git commits touching these files auto-flag this memory as [STALE].",
        ),
    ] = None,
    replaces_id: Annotated[
        int | None,
        Field(default=None, description="Optional explicit memory ID to supersede."),
    ] = None,
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


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def deprecate_memory(
    memory_id: Annotated[
        int,
        Field(
            description="Integer ID of the active or stale memory to retire/archive."
        ),
    ],
    reason: Annotated[
        str,
        Field(
            default="",
            description="Reason for deprecating the memory (e.g., 'replaced by microservice', 'obsolete config').",
        ),
    ] = "",
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


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def recall_history(
    scope: Annotated[
        str,
        Field(
            default="global",
            description="Project, repository, or directory name to retrieve historical audit trail for.",
        ),
    ] = "global",
    limit: Annotated[
        int,
        Field(
            default=10,
            ge=1,
            le=25,
            description="Maximum number of historical records to return (capped at 25).",
        ),
    ] = 10,
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
            tag = (
                f"superseded -> `#{r['superseded_by']}`"
                if r["superseded_by"]
                else "archived"
            )
            lines.append(
                f"- `#{r['id']}` [{tag}] ({r['valid_from']} to {r['valid_to']}): {subj}{r['content']}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Error retrieving history: {exc}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def revalidate_memories(
    memory_ids: Annotated[
        list[int],
        Field(
            description="List of stale memory IDs to revalidate and mark back as 'active'."
        ),
    ],
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


__all__ = [
    "COLD_START_ONBOARDING_NOTICE",
    "deprecate_memory",
    "recall_history",
    "recall_memories",
    "revalidate_memories",
    "save_memory",
]
