import os
from pathlib import Path


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        val = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got '{raw}'.") from exc
    if val < 1:
        raise ValueError(f"Environment variable {name} must be >= 1, got {val}.")
    return val


def get_memory_data_dir() -> Path:
    """Resolve MEMORY_DATA_DIR dynamically (default: Path('/data'))."""
    return Path(os.getenv("MEMORY_DATA_DIR", "/data"))


def get_api_key() -> str | None:
    """Resolve HELIOS_API_KEY dynamically (default: None -> open/local mode)."""
    val = os.getenv("HELIOS_API_KEY")
    if val is None or not val.strip():
        return None
    return val.strip()


def get_webhook_secret() -> str | None:
    """Resolve HELIOS_WEBHOOK_SECRET dynamically (default: None)."""
    val = os.getenv("HELIOS_WEBHOOK_SECRET") or os.getenv("WEBHOOK_SECRET")
    if val is None or not val.strip():
        return None
    return val.strip()


def get_word_limit() -> int:
    """Resolve HELIOS_WORD_LIMIT dynamically with integer validation (default: 25)."""
    return _get_int_env("HELIOS_WORD_LIMIT", 25)


def get_episodic_ttl_days() -> int:
    """Resolve HELIOS_EPISODIC_TTL_DAYS dynamically with integer validation (default: 14)."""
    return _get_int_env("HELIOS_EPISODIC_TTL_DAYS", 14)


def get_changelog_limit() -> int:
    """Resolve HELIOS_CHANGELOG_LIMIT dynamically with integer validation (default: 100)."""
    return _get_int_env("HELIOS_CHANGELOG_LIMIT", 100)


def get_allowed_origins() -> list[str]:
    """Resolve HELIOS_ALLOWED_ORIGINS dynamically into a list (default: ['*'])."""
    raw = os.getenv("HELIOS_ALLOWED_ORIGINS")
    if raw is None:
        raw = os.getenv("HELIOS_CORS_ORIGINS", "*")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins if origins else ["*"]


# Module-level dynamic attribute lookups via PEP 562 (__getattr__) so both
# `from src.config import get_word_limit` and `config.HELIOS_WORD_LIMIT`
# evaluate os.getenv dynamically at runtime.
def __getattr__(name: str):
    if name == "MEMORY_DATA_DIR":
        return get_memory_data_dir()
    if name == "HELIOS_API_KEY":
        return get_api_key()
    if name == "HELIOS_WEBHOOK_SECRET":
        return get_webhook_secret()
    if name == "HELIOS_WORD_LIMIT":
        return get_word_limit()
    if name == "HELIOS_EPISODIC_TTL_DAYS":
        return get_episodic_ttl_days()
    if name == "HELIOS_CHANGELOG_LIMIT":
        return get_changelog_limit()
    if name == "HELIOS_ALLOWED_ORIGINS":
        return get_allowed_origins()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
