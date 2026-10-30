"""Shared pytest fixtures and test environment configuration."""

import pytest
from starlette.testclient import TestClient

from src.db import init_db
from src.server import app


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
    init_db()


@pytest.fixture
def client():
    """Shared Starlette TestClient fixture for integration tests."""
    with TestClient(app) as test_client:
        yield test_client
