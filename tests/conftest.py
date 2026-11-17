"""Shared pytest fixtures and test environment configuration."""

import socket

import pytest
from starlette.testclient import TestClient

from src.db import init_db
from src.server import app

_ORIG_GETADDRINFO = socket.getaddrinfo


@pytest.fixture(autouse=True)
def isolated_helios_env(tmp_path, monkeypatch):
    """Isolate data directory to a temporary path and reset Helios environment before every test."""
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HELIOS_API_KEY", raising=False)
    monkeypatch.delenv("HELIOS_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("HELIOS_REQUIRE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("HELIOS_AUTO_SEED", raising=False)
    monkeypatch.delenv("HELIOS_WORD_LIMIT", raising=False)
    monkeypatch.delenv("HELIOS_EPISODIC_TTL_DAYS", raising=False)
    monkeypatch.delenv("HELIOS_CHANGELOG_LIMIT", raising=False)
    monkeypatch.delenv("HELIOS_PUBLIC_URL", raising=False)
    monkeypatch.delenv("HELIOS_GIT_PROVIDER", raising=False)
    monkeypatch.delenv("HELIOS_GIT_API_URL", raising=False)
    monkeypatch.delenv("HELIOS_GIT_TOKEN", raising=False)
    monkeypatch.delenv("HELIOS_GIT_OWNER", raising=False)
    monkeypatch.delenv("HELIOS_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("HELIOS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("HELIOS_CORS_ORIGINS", raising=False)

    def _test_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        host_str = (host.decode("utf-8") if isinstance(host, bytes) else str(host)).lower()
        if host_str.endswith((".example.com", ".internal.lan", ".mesh.lan", ".local")):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("192.0.2.1", int(port or 0)),
                )
            ]
        return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)

    monkeypatch.setattr(socket, "getaddrinfo", _test_getaddrinfo)
    init_db()


@pytest.fixture
def client():
    """Shared Starlette TestClient fixture for integration tests."""
    with TestClient(app) as test_client:
        yield test_client
