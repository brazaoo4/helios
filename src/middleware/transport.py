"""Unified ASGI dispatcher for Streamable HTTP and SSE transport."""

import re
import urllib.parse
from typing import Any

from src.tools import mcp, sse_app


class HybridMCPHandler:
    """
    Unified MCP ASGI dispatcher supporting both modern Streamable HTTP (POST /sse)
    and Server-Sent Events (GET /sse).
    """

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            method = scope.get("method", "GET")
            headers = dict(scope.get("headers", []))
            session_id_bytes = headers.get(b"mcp-session-id")

            # Check if this session is actively registered in Streamable HTTP
            has_active_streamable_session = False
            if session_id_bytes and hasattr(mcp, "session_manager"):
                try:
                    sid = session_id_bytes.decode("utf-8")
                    has_active_streamable_session = sid in getattr(
                        mcp.session_manager, "_server_instances", {}
                    )
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
                raw_qs = (
                    scope.get("query_string", b"").decode("utf-8", errors="ignore")
                )
                qparams = urllib.parse.parse_qs(raw_qs)
                token_val = qparams.get("token", [None])[0]
                if token_val:
                    enc_token = urllib.parse.quote(token_val, safe="").encode("utf-8")

                    async def send_with_token(message: dict[str, Any]) -> None:
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
    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if hasattr(mcp, "session_manager"):
            await mcp.session_manager.handle_request(scope, receive, send)
        else:
            await sse_app(scope, receive, send)


hybrid_handler = HybridMCPHandler()
streamable_handler = StreamableMCPHandler()

__all__ = [
    "HybridMCPHandler",
    "StreamableMCPHandler",
    "hybrid_handler",
    "streamable_handler",
]
