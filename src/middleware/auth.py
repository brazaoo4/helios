"""Zero-Trust ASGI security middleware and request body protection."""

import hmac
import logging
import time
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import get_allowed_origins, get_api_key
from src.db.connection import reset_client_id, set_client_id
from src.logging_config import sanitize_log_path

logger = logging.getLogger("helios.auth")
access_logger = logging.getLogger("helios.access")

MAX_WEBHOOK_BYTES = 1_048_576


class _PayloadTooLargeError(Exception):
    """Internal sentinel raised when a streamed request body exceeds MAX_WEBHOOK_BYTES."""


def _is_origin_allowed(origin: str) -> bool:
    """Validate browser Origin header against HELIOS_ALLOWED_ORIGINS."""
    allowed = get_allowed_origins()
    if "*" in allowed:
        return True
    return origin.lower() in [o.lower() for o in allowed]


def _constant_time_equals(candidate: str | None, secret: str | None) -> bool:
    if candidate is None or secret is None:
        return candidate is secret
    return hmac.compare_digest(candidate.encode("utf-8"), secret.encode("utf-8"))


def is_request_authenticated(request: Request) -> bool:
    """
    Validate request credentials against HELIOS_API_KEY using constant-time comparison.
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
        start_t = time.monotonic()
        status_code = 500
        client_label = (
            request.headers.get("x-helios-client", "").strip()
            or (request.client.host if request.client else "-")
        )

        async def logging_send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 200))
            await send(message)

        try:
            if path in ("/mcp", "/sse", "/messages") or path.startswith("/messages/") or path.startswith("/export/"):
                origin = request.headers.get("origin", "").strip()
                if origin and not _is_origin_allowed(origin):
                    logger.warning("Rejected %s %s due to untrusted Origin header: %s", request.method, path, origin)
                    response = JSONResponse(
                        {"status": "error", "message": "Forbidden: untrusted Origin header."},
                        status_code=403,
                    )
                    return await response(scope, receive, logging_send)

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
                return await self.app(scope, receive, logging_send)

            is_body_method = request.method in ("POST", "PUT", "PATCH")
            # Enforce payload limit on body-bearing requests
            if is_body_method:
                content_length = request.headers.get("content-length")
                if content_length is not None:
                    try:
                        parsed_len = int(content_length)
                    except ValueError:
                        response = JSONResponse(
                            {"status": "error", "message": "Invalid Content-Length header."},
                            status_code=400,
                        )
                        return await response(scope, receive, logging_send)
                    if parsed_len < 0:
                        response = JSONResponse(
                            {"status": "error", "message": "Invalid Content-Length header."},
                            status_code=400,
                        )
                        return await response(scope, receive, logging_send)
                    if parsed_len > MAX_WEBHOOK_BYTES:
                        logger.warning("Rejected %s %s with Content-Length %d (> 1MB)", request.method, path, parsed_len)
                        response = JSONResponse(
                            {"status": "error", "message": "Payload exceeds 1MB limit."},
                            status_code=413,
                        )
                        return await response(scope, receive, logging_send)

            is_webhook_route = request.method == "POST" and path in (
                "/webhook/git",
                "/webhook/forgejo",
                "/hooks/git-commit",
            )
            if not is_webhook_route and not is_request_authenticated(request):
                logger.warning("Rejected unauthenticated %s %s", request.method, path)
                response = JSONResponse(
                    {
                        "status": "error",
                        "message": "Unauthorized: missing or invalid API key.",
                    },
                    status_code=401,
                )
                return await response(scope, receive, logging_send)

            client_token = set_client_id(request.headers.get("x-helios-client", ""))
            try:
                if not is_body_method:
                    return await self.app(scope, receive, logging_send)

                bytes_received = 0
                limit_exceeded = False
                response_started = False

                async def bounded_receive() -> dict[str, Any]:
                    nonlocal bytes_received, limit_exceeded
                    message = await receive()
                    if message.get("type") == "http.request":
                        body = message.get("body", b"")
                        bytes_received += len(body)
                        if bytes_received > MAX_WEBHOOK_BYTES:
                            limit_exceeded = True
                            raise _PayloadTooLargeError()
                    return message

                async def guarded_send(message: dict[str, Any]) -> None:
                    nonlocal response_started
                    if limit_exceeded:
                        return
                    if message.get("type") == "http.response.start":
                        response_started = True
                    await logging_send(message)

                try:
                    await self.app(scope, bounded_receive, guarded_send)
                except _PayloadTooLargeError:
                    pass
                except BaseException as exc:
                    if not limit_exceeded:
                        raise
                    if isinstance(exc, BaseExceptionGroup):
                        _, rest = exc.split(_PayloadTooLargeError)
                        if rest is not None:
                            raise rest

                if limit_exceeded and not response_started:
                    logger.warning("Rejected streamed %s %s exceeding 1MB cap (%d bytes)", request.method, path, bytes_received)
                    response = JSONResponse(
                        {"status": "error", "message": "Payload exceeds 1MB limit."},
                        status_code=413,
                    )
                    return await response(scope, receive, logging_send)
            finally:
                reset_client_id(client_token)
        finally:
            duration_ms = (time.monotonic() - start_t) * 1000.0
            safe_target = sanitize_log_path(path, scope.get("query_string", b""))
            if path == "/health" and status_code < 400:
                access_logger.debug(
                    "%s %s -> %d (%.1fms, client=%s)",
                    request.method,
                    safe_target,
                    status_code,
                    duration_ms,
                    client_label,
                )
            elif status_code >= 400:
                access_logger.warning(
                    "%s %s -> %d (%.1fms, client=%s)",
                    request.method,
                    safe_target,
                    status_code,
                    duration_ms,
                    client_label,
                )
            else:
                access_logger.info(
                    "%s %s -> %d (%.1fms, client=%s)",
                    request.method,
                    safe_target,
                    status_code,
                    duration_ms,
                    client_label,
                )


__all__ = [
    "AuthGateMiddleware",
    "MAX_WEBHOOK_BYTES",
    "_read_bounded_body",
    "is_request_authenticated",
]
