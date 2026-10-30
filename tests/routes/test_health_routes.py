"""Tests for GET /health endpoint, status telemetry, and auth-aware redaction."""

from starlette.testclient import TestClient

from src.server import app


def test_health_endpoint_open_mode():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["service"] == "helios"
        assert data["database"]["connected"] is True
        assert data["database"]["journal_mode"] == "wal"
        assert data["database"]["active_memories"] == 0


def test_health_endpoint_redaction_when_api_key_set(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "super-secret-api-key")

    with TestClient(app) as client:
        # 1. Unauthenticated request -> 200 minimal JSON (no database telemetry)
        res_unauth = client.get("/health")
        assert res_unauth.status_code == 200
        assert res_unauth.json() == {"status": "healthy", "service": "helios"}
        assert "database" not in res_unauth.json()

        # 2. Authenticated via Bearer header -> full telemetry
        res_bearer = client.get(
            "/health",
            headers={"Authorization": "Bearer super-secret-api-key"},
        )
        assert res_bearer.status_code == 200
        data_bearer = res_bearer.json()
        assert "database" in data_bearer
        assert data_bearer["database"]["journal_mode"] == "wal"
        assert data_bearer["database"]["active_memories"] == 0

        # 3. Authenticated via ?token= query param -> full telemetry
        res_token = client.get("/health?token=super-secret-api-key")
        assert res_token.status_code == 200
        assert "database" in res_token.json()


def test_health_endpoint_database_error(monkeypatch):
    import src.routes.health as health_mod

    def _broken_query():
        raise RuntimeError("Database connection timed out")

    monkeypatch.setattr(health_mod, "_query_health_status", _broken_query)

    # 1. Open mode (unauthenticated, open mesh) -> 503 with error
    with TestClient(app) as client:
        res_open = client.get("/health")
        assert res_open.status_code == 503
        data_open = res_open.json()
        assert data_open["status"] == "unhealthy"
        assert "Database connection timed out" in data_open["error"]

    # 2. Authenticated mode with error telemetry
    monkeypatch.setenv("HELIOS_API_KEY", "secret-test-token")
    with TestClient(app) as client:
        # Unauthenticated request when key set -> 503 redacted
        res_unauth = client.get("/health")
        assert res_unauth.status_code == 503
        assert res_unauth.json() == {"status": "unhealthy", "service": "helios"}

        # Authenticated request -> 503 full error details
        res_auth = client.get("/health?token=secret-test-token")
        assert res_auth.status_code == 503
        data_auth = res_auth.json()
        assert data_auth["status"] == "unhealthy"
        assert "Database connection timed out" in data_auth["error"]
