"""Tests for structured logging, secret/query redaction, and HTTP access logs."""

import io
import json
import logging
import sys

from starlette.testclient import TestClient

from src.logging_config import configure_logging, sanitize_log_path
from src.server import app


def test_sanitize_log_path_redacts_sensitive_query_params_and_preserves_safe():
    """Sensitive query keys and embedded token patterns must be scrubbed."""
    fake_google_key = "AIzaSy" + ("A" * 33)
    sanitized = sanitize_log_path(
        "/messages/",
        f"client=cursor&token=super-secret-token&session_id=abc123&api_key={fake_google_key}&flag",
    )
    assert "super-secret-token" not in sanitized
    assert fake_google_key not in sanitized
    assert "client=cursor" in sanitized
    assert "session_id=abc123" in sanitized
    assert "flag" in sanitized
    assert "token=[REDACTED]" in sanitized
    assert "api_key=[REDACTED]" in sanitized

    assert sanitize_log_path("/health", b"") == "/health"
    assert sanitize_log_path("/setup", "secret=value") == "/setup?secret=[REDACTED]"


def test_configure_logging_text_and_secret_redaction(monkeypatch):
    """Text formatter emits leveled messages and redacts embedded secrets and tracebacks."""
    monkeypatch.setenv("HELIOS_LOG_LEVEL", "INFO")
    monkeypatch.setenv("HELIOS_LOG_FORMAT", "text")
    buf = io.StringIO()
    logger = configure_logging(stream=buf)

    assert logger.name == "helios"
    assert logger.level == logging.INFO
    assert logger.propagate is False

    fake_google_key = "AIzaSy" + ("B" * 33)
    test_logger = logging.getLogger("helios.test")
    test_logger.info("Leak check token %s", fake_google_key)
    test_logger.debug("Should be filtered at INFO")
    try:
        raise RuntimeError("Failure with Bearer abcdef1234567890")
    except RuntimeError:
        test_logger.error("Boom", exc_info=True)

    output = buf.getvalue()
    assert "Leak check token [REDACTED]" in output
    assert fake_google_key not in output
    assert "Should be filtered at INFO" not in output
    assert "Bearer [REDACTED]" in output
    assert "abcdef1234567890" not in output


def test_configure_logging_json_and_invalid_level_fallback(monkeypatch):
    """JSON formatter emits parseable JSON lines; invalid levels fall back to INFO."""
    monkeypatch.setenv("HELIOS_LOG_LEVEL", "NOT_A_LEVEL")
    monkeypatch.setenv("HELIOS_LOG_FORMAT", "json")
    buf = io.StringIO()
    logger = configure_logging(stream=buf)

    assert logger.level == logging.INFO

    fake_ghp = "ghp_" + ("0123456789abcdef" * 2) + "0123"
    access_logger = logging.getLogger("helios.access")
    try:
        raise ValueError(f"Bad auth {fake_ghp}")
    except ValueError:
        access_logger.warning("Auth denied", exc_info=True)

    lines = [line for line in buf.getvalue().strip().splitlines() if line]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "helios.access"
    assert payload["msg"] == "Auth denied"
    assert "exc" in payload
    assert fake_ghp not in payload["exc"]
    assert "[REDACTED]" in payload["exc"]


def test_http_access_logging_levels_and_token_redaction(monkeypatch):
    """AuthGateMiddleware logs /health at DEBUG, auth failures at WARNING, and scrubs ?token=."""
    monkeypatch.setenv("HELIOS_API_KEY", "test-api-key-value")
    monkeypatch.setenv("HELIOS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("HELIOS_LOG_FORMAT", "text")
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)

    with TestClient(app) as client:
        # 200 /health logged at DEBUG
        res_health = client.get("/health")
        assert res_health.status_code == 200

        # 401 logged at WARNING without leaking supplied token
        res_denied = client.get("/export/markdown?token=wrong-secret")
        assert res_denied.status_code == 401

        # 200 authenticated with query token + client attribution
        res_ok = client.get(
            "/export/markdown?token=test-api-key-value&scope=global",
            headers={"X-Helios-Client": "cursor-ci"},
        )
        assert res_ok.status_code == 200

    logs = buf.getvalue()
    assert "Helios ready:" in logs
    assert "Helios shutdown complete" in logs
    assert "GET /health -> 200" in logs
    assert "DEBUG" in logs
    assert "WARNING" in logs
    assert "wrong-secret" not in logs
    assert "test-api-key-value" not in logs
    assert "token=[REDACTED]" in logs
    assert "scope=global" in logs
    assert "cursor-ci" in logs
