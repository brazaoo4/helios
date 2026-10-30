"""Universal Git Webhook Adapter for GitHub, Forgejo/Gitea, and GitLab."""

import hashlib
import hmac
import json
import os
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import get_api_key, get_webhook_secret
from src.db import flag_stale_by_files
from src.exporter import sync_markdown_exports
from src.middleware.auth import MAX_WEBHOOK_BYTES, _read_bounded_body


def verify_forgejo_signature(
    raw_body: bytes, signature_header: str, secret: str
) -> bool:
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
    return hmac.compare_digest(
        expected_signature.encode("utf-8"), sig_clean.encode("utf-8")
    )


def verify_github_signature(
    raw_body: bytes, signature_header: str, secret: str
) -> bool:
    if not signature_header:
        return False
    sig_clean = signature_header.strip()
    if not sig_clean.startswith("sha256="):
        return False
    expected_signature = (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(
        expected_signature.encode("utf-8"), sig_clean.encode("utf-8")
    )


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
    forgejo_sig = (
        headers.get("X-Forgejo-Signature") or headers.get("X-Gitea-Signature") or ""
    )
    gitlab_token = headers.get("X-Gitlab-Token", "")
    auth_header = headers.get("Authorization", "").strip()

    # Determine provider
    if "X-Gitlab-Event" in headers or "X-Gitlab-Token" in headers:
        provider = "gitlab"
    elif (
        "X-Forgejo-Event" in headers
        or "X-Forgejo-Signature" in headers
        or "X-Gitea-Event" in headers
        or "X-Gitea-Signature" in headers
    ):
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
    if gitlab_token and hmac.compare_digest(
        gitlab_token.strip().encode("utf-8"), webhook_secret.encode("utf-8")
    ):
        return provider, True

    # 4. Generic Authorization: Bearer <secret>
    if auth_header and hmac.compare_digest(
        auth_header.encode("utf-8"), f"Bearer {webhook_secret}".encode()
    ):
        return provider, True

    return provider, False


def _is_push_event(
    request: Request, payload: dict[str, Any] | None = None
) -> tuple[bool, str]:
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


def _process_webhook_drift(
    repo_name: str, changed_files: list[str], commit_sha: str
) -> int:
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
    raw_body = await _read_bounded_body(request, max_bytes=MAX_WEBHOOK_BYTES)
    if raw_body is None:
        return JSONResponse(
            {"status": "error", "message": "Payload exceeds 1MB limit."},
            status_code=413,
        )

    webhook_secret = get_webhook_secret()
    has_api_key = get_api_key() is not None
    req_sec_env = os.getenv("HELIOS_REQUIRE_WEBHOOK_SECRET")
    if req_sec_env is None:
        require_secret = has_api_key
    else:
        require_secret = req_sec_env.lower() in ("1", "true", "yes")

    if require_secret and not webhook_secret:
        return JSONResponse(
            {
                "status": "error",
                "message": "HELIOS_WEBHOOK_SECRET is not configured on the server.",
            },
            status_code=503,
        )

    provider, is_valid = _detect_webhook_provider_and_verify(
        request, raw_body, webhook_secret
    )
    if not is_valid:
        return JSONResponse(
            {"status": "error", "message": "Invalid or missing webhook signature."},
            status_code=401,
        )

    # Check event header before parsing body if header is present
    is_push_hdr, event_name_hdr = _is_push_event(request)
    if not is_push_hdr:
        return JSONResponse(
            {
                "status": "ignored",
                "provider": provider,
                "message": f"Event '{event_name_hdr}' ignored (only 'push' triggers drift detection).",
            },
            status_code=200,
        )

    if not raw_body or not raw_body.strip():
        return JSONResponse(
            {"status": "error", "message": "Empty webhook payload."},
            status_code=400,
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return JSONResponse(
            {"status": "error", "message": "Malformed JSON payload."},
            status_code=400,
        )

    if not isinstance(payload, dict) or not payload:
        return JSONResponse(
            {"status": "error", "message": "Empty or invalid JSON payload."},
            status_code=400,
        )

    is_push, event_name = _is_push_event(request, payload)
    if not is_push:
        return JSONResponse(
            {
                "status": "ignored",
                "provider": provider,
                "message": f"Event '{event_name}' ignored (only 'push' triggers drift detection).",
            },
            status_code=200,
        )

    repo_info = payload.get("repository") or {}
    project_info = payload.get("project") or {}
    repo_name = ""
    if isinstance(repo_info, dict):
        repo_name = (
            repo_info.get("name")
            or repo_info.get("full_name")
            or repo_info.get("path_with_namespace")
            or ""
        )
    if not repo_name and isinstance(project_info, dict):
        repo_name = (
            project_info.get("name")
            or project_info.get("path_with_namespace")
            or ""
        )

    if not repo_name:
        return JSONResponse(
            {"status": "error", "message": "Missing repository name in payload."},
            status_code=400,
        )

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


forgejo_webhook = git_webhook

__all__ = [
    "_detect_webhook_provider_and_verify",
    "_is_push_event",
    "_process_webhook_drift",
    "forgejo_webhook",
    "git_webhook",
    "verify_forgejo_signature",
    "verify_github_signature",
]
