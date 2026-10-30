"""Zero-Trust ASGI security middleware and request body protection."""

import hashlib
import hmac
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import get_api_key

MAX_WEBHOOK_BYTES = 1_048_576


def _constant_time_equals(candidate: str | None, secret: str | None) -> bool:
    if candidate is None or secret is None:
        return candidate is secret
    c_digest = hashlib.sha256(candidate.encode("utf-8")).digest()
    s_digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return hmac.compare_digest(c_digest, s_digest)


def is_request_authenticated(request: Request) -> bool:
    """
    Validate request credentials against HELIOS_API_KEY using constant-time digest comparison.
    Returns True if HELIOS_API_KEY is unset (open local/mesh mode) or if credentials match:
      1. Header: `Authorization: Bearer <key>`
      2. Query Parameter: `?token=<key>`
    """
    api_key = get_api_key()
    if not api_key:
        return True

    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header:
        if auth_header.lower().startswith("bearer "):
            candidate_bearer = auth_header[7:].strip()
            return bool(candidate_bearer) and _constant_time_equals(candidate_bearer, api_key)
        return False

    query_token = request.query_params.get("token", "").strip()
    if query_token:
        return _constant_time_equals(query_token, api_key)

    return False


async def _read_bounded_body(
    request: Request, max_bytes: int = MAX_WEBHOOK_BYTES, timeout_seconds: float = 15.0
) -> bytes | None:
    """Read incoming request body with strict size limit enforcement and slow-drip timeout."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return None
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    try:
        with anyio.fail_after(timeout_seconds):
            async for chunk in request.stream():
                total += len(chunk)
                if total > max_bytes:
                    return None
                chunks.append(chunk)
    except TimeoutError:
        return None
    return b"".join(chunks)


class AuthGateMiddleware:
    """
    Zero-Trust Security Middleware (Pure ASGI):
    - If HELIOS_API_KEY is unset, passes all requests (open local/mesh mode).
    - If set, enforces constant-time authentication via Authorization: Bearer <key> or ?token=<key>.
    - Exempts specific webhook routes, GET /health, and GET /setup*.
    - Pure ASGI implementation ensures compatibility with SSE and streaming HTTP responses
      without Starlette BaseHTTPMiddleware response-wrapping assertion crashes.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        if request.method == "OPTIONS":
            return await self.app(scope, receive, send)

        path = request.url.path
        if request.method == "GET" and (
            path == "/health"
            or path
            in (
                "/setup",
                "/setup.ps1",
                "/setup.sh",
                "/uninstall",
                "/uninstall.ps1",
                "/uninstall.sh",
            )
        ):
            return await self.app(scope, receive, send)

        # Enforce payload limit on POST requests
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_WEBHOOK_BYTES:
                        response = JSONResponse(
                            {"status": "error", "message": "Payload exceeds 1MB limit."},
                            status_code=413,
                        )
                        return await response(scope, receive, send)
                except ValueError:
                    pass

        if request.method == "POST" and path in (
            "/webhook/git",
            "/webhook/forgejo",
            "/hooks/git-commit",
        ):
            return await self.app(scope, receive, send)

        if not is_request_authenticated(request):
            response = JSONResponse(
                {
                    "status": "error",
                    "message": "Unauthorized: missing or invalid API key.",
                },
                status_code=401,
            )
            return await response(scope, receive, send)

        return await self.app(scope, receive, send)


__all__ = [
    "AuthGateMiddleware",
    "MAX_WEBHOOK_BYTES",
    "_read_bounded_body",
    "is_request_authenticated",
]
