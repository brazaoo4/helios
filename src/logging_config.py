"""Structured, token-redacting logging configuration for Helios."""

import json
import logging
import os
import sys
import urllib.parse
from datetime import UTC, datetime

from src.security_gate import redact_secrets

_SENSITIVE_QUERY_KEYS = frozenset({"token", "key", "api_key", "secret", "password", "auth"})


class _JsonLogFormatter(logging.Formatter):
    """Compact single-line JSON log formatter for container log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_secrets(record.getMessage()),
        }
        if record.exc_info:
            payload["exc"] = redact_secrets(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


class _RedactingTextFormatter(logging.Formatter):
    """Single-line UTC text log formatter with automatic secret redaction."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        msg = redact_secrets(record.getMessage())
        line = f"{ts} {record.levelname:<7} [{record.name}] {msg}"
        if record.exc_info:
            line += "\n" + redact_secrets(self.formatException(record.exc_info))
        return line


def sanitize_log_path(path: str, query_string: bytes | str = b"") -> str:
    """Return path + query string with sensitive query parameter values redacted."""
    raw_qs = (
        query_string.decode("utf-8", errors="ignore")
        if isinstance(query_string, bytes)
        else str(query_string or "")
    )
    if not raw_qs:
        return redact_secrets(path)

    redacted_parts: list[str] = []
    for part in raw_qs.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            key_norm = urllib.parse.unquote(k).strip().lower()
            if key_norm in _SENSITIVE_QUERY_KEYS:
                redacted_parts.append(f"{k}=[REDACTED]")
            else:
                redacted_parts.append(f"{k}={redact_secrets(v)}")
        elif part:
            redacted_parts.append(redact_secrets(part))

    qs_str = "&".join(redacted_parts)
    return f"{redact_secrets(path)}?{qs_str}" if qs_str else redact_secrets(path)


def configure_logging(stream: object | None = None) -> logging.Logger:
    """
    Configure the 'helios' logger hierarchy from HELIOS_LOG_LEVEL and HELIOS_LOG_FORMAT.
    Idempotent across repeated calls (e.g. FastAPI/Starlette TestClient lifespans).
    """
    raw_level = (os.getenv("HELIOS_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, raw_level, None)
    if not isinstance(level, int):
        level = logging.INFO

    log_format = (os.getenv("HELIOS_LOG_FORMAT") or "text").strip().lower()
    formatter: logging.Formatter = (
        _JsonLogFormatter() if log_format == "json" else _RedactingTextFormatter()
    )

    helios_logger = logging.getLogger("helios")
    helios_logger.setLevel(level)
    helios_logger.propagate = False

    for existing in list(helios_logger.handlers):
        helios_logger.removeHandler(existing)

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    helios_logger.addHandler(handler)

    if level >= logging.INFO:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    return helios_logger


__all__ = [
    "configure_logging",
    "sanitize_log_path",
]
