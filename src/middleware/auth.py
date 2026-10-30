"""Zero-Trust ASGI security middleware and request body protection."""

import hmac
import uuid
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import get_api_key
from src.tools import sse_app

MAX_WEBHOOK_BYTES = 1_048_576


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
        if candidate_bearer and hmac.compare_digest(
            candidate_bearer.encode("utf-8"), api_key.encode("utf-8")
        ):
            return True

    query_token = request.query_params.get("token", "").strip()
    if query_token and hmac.compare_digest(
        query_token.encode("utf-8"), api_key.encode("utf-8")
    ):
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


async def _read_bounded_body(
    request: Request, max_bytes: int = MAX_WEBHOOK_BYTES
) -> bytes | None:
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


class AuthGateMiddleware:
    """
    Zero-Trust Security Middleware (Pure ASGI):
    - If HELIOS_API_KEY is unset, passes all requests (open local/mesh mode).
    - If set, enforces constant-time authentication via Authorization: Bearer <key> or ?token=<key>.
    - Exempts POST /webhook/* (and /hooks/git-commit), GET /health, and GET /setup*.
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

        if request.method == "POST" and (
            path.startswith("/webhook/") or path == "/hooks/git-commit"
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
