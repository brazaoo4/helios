"""Tests for AuthGateMiddleware and ASGI authentication lifecycle."""

from starlette.testclient import TestClient

from src.server import app, save_memory


def test_auth_gate_middleware(monkeypatch):
    api_key = "zero-trust-token-999"
    monkeypatch.setenv("HELIOS_API_KEY", api_key)
    save_memory(scope="global", category="rule", content="Always authenticate public endpoints")

    with TestClient(app) as client:
        # Missing token -> 401
        res_missing = client.get("/export/markdown")
        assert res_missing.status_code == 401

        # Invalid Bearer token -> 401
        res_invalid_bearer = client.get(
            "/export/markdown",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert res_invalid_bearer.status_code == 401

        # Invalid query token -> 401
        res_invalid_query = client.get("/export/markdown?token=wrong-token")
        assert res_invalid_query.status_code == 401

        # Valid Bearer header -> 200
        res_valid_bearer = client.get(
            "/export/markdown",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert res_valid_bearer.status_code == 200
        assert "exports" in res_valid_bearer.json()

        # Valid ?token= query parameter -> 200
        res_valid_query = client.get(f"/export/markdown?token={api_key}")
        assert res_valid_query.status_code == 200
        assert "exports" in res_valid_query.json()

        # MCP /mcp endpoint requires auth when HELIOS_API_KEY is set
        res_mcp_unauth = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert res_mcp_unauth.status_code == 401


def test_auth_gate_middleware_pure_asgi_sse_stream():
    with TestClient(app) as client:
        with client.stream("GET", "/sse") as res:
            assert res.status_code == 200


def test_auth_gate_middleware_options_bypass(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "secret-key-123")
    with TestClient(app) as client:
        # OPTIONS request should bypass auth gate
        res = client.options("/export/markdown")
        # Starlette default for OPTIONS or route response
        assert res.status_code != 401


def test_read_bounded_body():
    import anyio
    from starlette.requests import Request

    from src.middleware.auth import _read_bounded_body

    # 1. Normal body within limits
    async def run_test():
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"content-length", b"5")],
        }

        async def receive_normal():
            return {"type": "http.request", "body": b"hello", "more_body": False}

        req = Request(scope, receive_normal)
        body = await _read_bounded_body(req, max_bytes=10)
        assert body == b"hello"

        # 2. Content-Length exceeds max_bytes
        scope_too_large = {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"content-length", b"100")],
        }
        req_large = Request(scope_too_large, receive_normal)
        assert await _read_bounded_body(req_large, max_bytes=10) is None

        # 3. Stream exceeds max_bytes without content-length
        scope_no_len = {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"content-length", b"invalid")],
        }

        async def receive_stream():
            return {"type": "http.request", "body": b"chunk-that-is-too-long", "more_body": False}

        req_stream = Request(scope_no_len, receive_stream)
        assert await _read_bounded_body(req_stream, max_bytes=5) is None

    anyio.run(run_test)
