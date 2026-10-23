import contextlib
import hashlib
import hmac
import json
import os
from typing import AsyncGenerator

import anyio
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.sse import TransportSecuritySettings
except ImportError:
    from fastmcp import FastMCP
    TransportSecuritySettings = None

from src.config import (
    get_allowed_origins,
    get_api_key,
    get_webhook_secret,
)
from src.db import (
    deprecate_memory as db_deprecate_memory,
    flag_stale_by_files,
    get_connection,
    init_db,
    list_aliases,
    query_memories,
    remove_alias,
    resolve_scope,
    set_alias,
    upsert_memory,
)
from src.exporter import (
    create_portable_archive,
    get_export_dir,
    sync_markdown_exports,
)
from src.seed import ingest_declarative_seed_files, is_db_empty, seed_if_empty

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
    and legacy Server-Sent Events (GET /sse).
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

        # Fall through to legacy SSE app for GET /sse without active streamable session
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
    "Please prompt the user for project context or inspect baseline project configuration files "
    "(e.g., README.md, package.json, compose.yaml, pyproject.toml) to seed initial architectural rules and facts "
    "using save_memory()."
)


# 2. FastMCP Tool Definitions
@mcp.tool()
def recall_memories(
    scope: str = "global",
    query: str = "",
    limit: int = 8,
    include_global: bool = True,
) -> str:
    """
    Recall active memories from Helios using FTS5 BM25 search.
    """
    try:
        memories = query_memories(
            raw_scope=scope,
            query=query,
            include_global=include_global,
            limit=limit,
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
    scope: str,
    category: str,
    content: str,
    subject: str = "",
    anchor_files: list[str] | None = None,
    replaces_id: int | None = None,
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
    memory_id: int,
    reason: str = "",
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
    scope: str = "global",
    limit: int = 10,
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
def manage_scope_alias(alias: str = "", canonical_scope: str = "", action: str = "set") -> str:
    """
    Manage project and folder aliases mapping to canonical memory scopes.
    - action='set': Maps alias -> canonical_scope (e.g. 'frontend-v2' -> 'web').
    - action='remove': Deletes an existing alias mapping.
    - action='list': Returns all current alias-to-scope mappings.
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
            if not mappings:
                return "No scope aliases configured."
            lines = [f"- `{k}` -> `{v}`" for k, v in mappings.items()]
            return "\n".join(lines)
        else:
            return f"Invalid action '{action}'. Must be 'set', 'remove', or 'list'."
    except Exception as exc:
        return f"Error managing scope alias: {exc}"


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

    return False


class AuthGateMiddleware(BaseHTTPMiddleware):
    """
    Zero-Trust Security Middleware:
    - If HELIOS_API_KEY is unset, passes all requests (open local/mesh mode).
    - If set, enforces constant-time authentication via Authorization: Bearer <key> or ?token=<key>.
    - Exempts POST /webhook/* (and /hooks/git-commit) and GET /health.
    """
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if request.method == "GET" and path == "/health":
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


async def git_webhook(request: Request) -> JSONResponse:
    """
    Universal Git Webhook Adapter (`POST /webhook/git` & `POST /webhook/forgejo`).
    Supports GitHub, Forgejo/Gitea, and GitLab push events.
    """
    raw_body = await request.body()
    if len(raw_body) > 1_048_576:
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


# 6. Assemble Starlette ASGI Application
starlette_routes = [
    Route("/health", health_check, methods=["GET"]),
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
