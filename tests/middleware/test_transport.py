"""Tests for MCP transport security, hybrid SSE/Streamable endpoints, and session fallback."""

import anyio
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.testclient import TestClient

from src.server import app, hybrid_handler, mcp


def test_transport_security_allows_reverse_proxy_domain():
    t = SseServerTransport("/messages", security_settings=mcp.settings.transport_security)
    req = Request({"type": "http", "method": "GET", "headers": [(b"host", b"helios.example.com")]})
    res = anyio.run(t._security.validate_request, req, False)
    assert res is None


def test_hybrid_mcp_endpoints():
    with TestClient(app) as client:
        # 1. Test Streamable HTTP POST /sse (Antigravity IDE connection)
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        res_sse_post = client.post(
            "/sse",
            json=init_payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert res_sse_post.status_code == 200
        session_id = res_sse_post.headers.get("mcp-session-id")
        assert session_id is not None

        # 2. Test Streamable HTTP POST /mcp
        res_mcp_post = client.post(
            "/mcp",
            json=init_payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert res_mcp_post.status_code == 200


def test_hybrid_mcp_stale_session_fallback():
    # When a client sends a GET request with an expired/stale mcp-session-id,
    # it must fall back to standard SSE (sse_app) rather than returning 404 Session Not Found.
    messages_sent = []

    async def fake_send(message):
        messages_sent.append(message)

    async def fake_receive():
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/sse",
        "headers": [(b"mcp-session-id", b"stale_session_12345")],
    }
    anyio.run(hybrid_handler, scope, fake_receive, fake_send)
    assert any(m.get("type") == "http.response.start" and m.get("status") == 200 for m in messages_sent)


def test_hybrid_mcp_sse_token_injection():
    messages_sent = []

    async def fake_send(message):
        messages_sent.append(message)

    async def fake_receive():
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/sse",
        "query_string": b"token=test-query-token-123",
        "headers": [],
    }
    anyio.run(hybrid_handler, scope, fake_receive, fake_send)
    assert any(m.get("type") == "http.response.start" and m.get("status") == 200 for m in messages_sent)

