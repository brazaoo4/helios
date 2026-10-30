import ipaddress
import os
import urllib.parse
from pathlib import Path
from typing import Any

LOCKED_SECURITY_KEYS: set[str] = {
    "MEMORY_DATA_DIR",
    "HELIOS_API_KEY",
    "HELIOS_WEBHOOK_SECRET",
    "HELIOS_ALLOWED_ORIGINS",
    "HELIOS_REQUIRE_WEBHOOK_SECRET",
    "WEBHOOK_SECRET",
    "HELIOS_CORS_ORIGINS",
}

MUTABLE_SETTINGS: dict[str, dict[str, Any]] = {
    "HELIOS_WORD_LIMIT": {
        "type": int,
        "default": 25,
        "min": 5,
        "max": 200,
        "sensitive": False,
        "description": "Maximum word count per atomic memory in AUDN write gate (5-200).",
    },
    "HELIOS_EPISODIC_TTL_DAYS": {
        "type": int,
        "default": 14,
        "min": 1,
        "max": 365,
        "sensitive": False,
        "description": "Inactivity days before episodic memories are auto-archived (1-365).",
    },
    "HELIOS_CHANGELOG_LIMIT": {
        "type": int,
        "default": 100,
        "min": 10,
        "max": 1000,
        "sensitive": False,
        "description": "Maximum historical changelog records retained per scope export (10-1000).",
    },
    "HELIOS_PUBLIC_URL": {
        "type": str,
        "default": "",
        "sensitive": False,
        "description": "Public/mesh base URL override for setup generation (e.g. https://helios.example.com).",
    },
    "HELIOS_GIT_PROVIDER": {
        "type": str,
        "default": "",
        "choices": ("", "forgejo", "gitea", "github", "gitlab"),
        "sensitive": False,
        "description": "Git provider for webhook drift tracking ('forgejo', 'gitea', 'github', 'gitlab').",
    },
    "HELIOS_GIT_API_URL": {
        "type": str,
        "default": "",
        "sensitive": False,
        "description": "Base URL of Git provider API.",
    },
    "HELIOS_GIT_OWNER": {
        "type": str,
        "default": "",
        "sensitive": False,
        "description": "Target Git username or organization for repository management.",
    },
    "HELIOS_GIT_TOKEN": {
        "type": str,
        "default": None,
        "sensitive": True,
        "description": "Personal Access Token for Git provider API.",
    },
    "HELIOS_WEBHOOK_URL": {
        "type": str,
        "default": "",
        "sensitive": False,
        "description": "Target URL registered on Git providers (e.g. https://helios.example.com/webhook/git).",
    },
}


def validate_http_url(url: str, allow_loopback: bool = False) -> str:
    """
    Validate that an HTTP/HTTPS URL is well-formed, safe, and not pointing to
    forbidden destinations (cloud metadata services, loopback if disallowed).
    Allows RFC1918 LAN IPs, Tailscale (100.*), and Docker service hostnames.
    """
    cleaned = str(url).strip()
    if not cleaned:
        return ""

    for ch in ('"', "'", "`", "$", "(", ")", " ", "\t", "\n", "\r", "\\"):
        if ch in cleaned:
            raise ValueError(f"URL contains invalid characters: {cleaned!r}")

    parsed = urllib.parse.urlsplit(cleaned)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got '{parsed.scheme}'.")

    if not parsed.netloc or not parsed.hostname:
        raise ValueError("URL must include a valid host/netloc.")

    if parsed.username or parsed.password:
        raise ValueError("URL must not contain embedded user credentials.")

    if parsed.fragment:
        raise ValueError("URL must not contain a URL fragment.")

    host = parsed.hostname.lower()

    if host == "metadata.google.internal" or host.startswith("metadata."):
        raise ValueError(f"Access to cloud metadata host '{host}' is forbidden.")

    try:
        ip = ipaddress.ip_address(host)
        v4 = ip.ipv4_mapped if (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped) else ip
        if ip.is_link_local or v4.is_link_local or host.startswith("169.254.") or str(v4) == "100.100.100.200":
            raise ValueError(f"Access to link-local/cloud metadata IP '{host}' is forbidden.")
        in_zero_net = isinstance(v4, ipaddress.IPv4Address) and v4 in ipaddress.ip_network("0.0.0.0/8")
        if not allow_loopback and (ip.is_loopback or v4.is_loopback or ip.is_unspecified or in_zero_net):
            raise ValueError(f"Loopback IP address '{host}' is forbidden.")
    except ValueError as exc:
        if "forbidden" in str(exc):
            raise
        if host.startswith("169.254."):
            raise ValueError(f"Access to link-local/cloud metadata host '{host}' is forbidden.")
        if any(part.isdigit() or part.lower().startswith("0x") for part in host.split(".") if part):
            raise ValueError(f"Non-standard numeric IP literal '{host}' is forbidden.")
        if not allow_loopback and (host == "localhost" or host.endswith(".localhost") or host == "0.0.0.0"):
            raise ValueError(f"Loopback host '{host}' is forbidden.")

    clean_path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc, clean_path, parsed.query, ""))


def _get_setting_from_db(key: str) -> str | None:
    """Fetch setting from SQLite runtime_settings table, safely handling uninitialized DB."""
    try:
        from src.db import get_runtime_setting
        return get_runtime_setting(key)
    except Exception:
        return None


def validate_setting_value(key: str, raw_value: Any) -> Any:
    """Validate a setting value against allowed types, ranges, and choices."""
    if key in LOCKED_SECURITY_KEYS:
        raise ValueError(f"Setting '{key}' is locked and can only be set via environment variable.")

    meta = MUTABLE_SETTINGS.get(key)
    if not meta:
        raise KeyError(f"Unknown setting '{key}'.")

    if meta["type"] is int:
        raw_str = str(raw_value).strip()
        try:
            val = int(raw_str)
        except ValueError as exc:
            raise ValueError(f"{key} must be an integer, got '{raw_value}'.") from exc
        if val < meta["min"] or val > meta["max"]:
            raise ValueError(f"{key} must be between {meta['min']} and {meta['max']}, got {val}.")
        return val

    elif key == "HELIOS_GIT_PROVIDER":
        val = str(raw_value).strip().lower() if raw_value is not None else ""
        if val not in meta["choices"]:
            raise ValueError(f"{key} must be one of {meta['choices']}, got '{raw_value}'.")
        return val

    elif key == "HELIOS_GIT_TOKEN":
        if raw_value is None:
            return None
        val = str(raw_value).strip()
        return val if val else None

    elif key in ("HELIOS_GIT_API_URL", "HELIOS_WEBHOOK_URL"):
        return validate_http_url(str(raw_value) if raw_value is not None else "", allow_loopback=False)

    elif key == "HELIOS_PUBLIC_URL":
        return validate_http_url(str(raw_value) if raw_value is not None else "", allow_loopback=True)

    else:
        return str(raw_value).strip() if raw_value is not None else ""


def resolve_setting_with_source(key: str) -> tuple[Any, str]:
    """
    Resolve setting value with provenance:
    Returns (value, source) where source is 'db', 'env', or 'default'.
    """
    meta = MUTABLE_SETTINGS.get(key)
    if not meta:
        raise KeyError(f"Unknown setting '{key}'.")

    # 1. Check SQLite runtime_settings table
    db_val = _get_setting_from_db(key)
    if db_val is not None:
        try:
            val = validate_setting_value(key, db_val)
            return val, "db"
        except ValueError:
            pass

    # 2. Check environment variable
    env_raw = os.getenv(key)
    if env_raw is not None and env_raw.strip():
        if meta["type"] is int:
            try:
                int_val = int(env_raw.strip())
            except ValueError as exc:
                raise ValueError(f"Environment variable {key} must be an integer, got '{env_raw}'.") from exc
            if int_val < 1:
                raise ValueError(f"Environment variable {key} must be >= 1, got {int_val}.")
            if "min" in meta and int_val < meta["min"]:
                raise ValueError(f"Environment variable {key} must be >= {meta['min']}, got {int_val}.")
            if "max" in meta and int_val > meta["max"]:
                raise ValueError(f"Environment variable {key} must be <= {meta['max']}, got {int_val}.")
            return int_val, "env"
        elif key == "HELIOS_GIT_PROVIDER":
            prov_val = env_raw.strip().lower()
            if prov_val and prov_val not in meta["choices"]:
                raise ValueError(f"Environment variable {key} must be one of {meta['choices']}, got '{env_raw}'.")
            return prov_val, "env"
        elif key == "HELIOS_GIT_TOKEN":
            tok_val = env_raw.strip()
            return tok_val if tok_val else None, "env"
        else:
            return env_raw.strip(), "env"

    # 3. Default
    return meta["default"], "default"


# --- Security-Locked Getters (Environment Only) ---

def get_memory_data_dir() -> Path:
    """Resolve MEMORY_DATA_DIR dynamically (default: Path('/data')). Environment-only."""
    return Path(os.getenv("MEMORY_DATA_DIR", "/data"))


def get_api_key() -> str | None:
    """Resolve HELIOS_API_KEY dynamically (default: None -> open mode). Environment-only."""
    val = os.getenv("HELIOS_API_KEY")
    if val is None or not val.strip():
        return None
    return val.strip()


def get_webhook_secret() -> str | None:
    """Resolve HELIOS_WEBHOOK_SECRET dynamically (default: None). Environment-only."""
    val = os.getenv("HELIOS_WEBHOOK_SECRET") or os.getenv("WEBHOOK_SECRET")
    if val is None or not val.strip():
        return None
    return val.strip()


def get_allowed_origins() -> list[str]:
    """Resolve HELIOS_ALLOWED_ORIGINS dynamically into a list (default: ['*']). Environment-only."""
    raw = os.getenv("HELIOS_ALLOWED_ORIGINS")
    if raw is None:
        raw = os.getenv("HELIOS_CORS_ORIGINS", "*")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins if origins else ["*"]


# --- Layered Getters (SQLite -> Environment -> Default) ---

def get_word_limit() -> int:
    """Resolve HELIOS_WORD_LIMIT dynamically (default: 25)."""
    val, _ = resolve_setting_with_source("HELIOS_WORD_LIMIT")
    return val


def get_episodic_ttl_days() -> int:
    """Resolve HELIOS_EPISODIC_TTL_DAYS dynamically (default: 14)."""
    val, _ = resolve_setting_with_source("HELIOS_EPISODIC_TTL_DAYS")
    return val


def get_changelog_limit() -> int:
    """Resolve HELIOS_CHANGELOG_LIMIT dynamically (default: 100)."""
    val, _ = resolve_setting_with_source("HELIOS_CHANGELOG_LIMIT")
    return val


def get_public_url() -> str:
    """Resolve HELIOS_PUBLIC_URL dynamically for client setup generation (default: '')."""
    val, _ = resolve_setting_with_source("HELIOS_PUBLIC_URL")
    return val


def get_git_provider() -> str:
    """Resolve HELIOS_GIT_PROVIDER dynamically (e.g. 'forgejo', 'gitea', 'github', 'gitlab')."""
    val, _ = resolve_setting_with_source("HELIOS_GIT_PROVIDER")
    return val


def get_git_api_url() -> str:
    """Resolve HELIOS_GIT_API_URL dynamically (e.g. 'https://forgejo.example.com')."""
    val, _ = resolve_setting_with_source("HELIOS_GIT_API_URL")
    return val


def get_git_owner() -> str:
    """Resolve HELIOS_GIT_OWNER dynamically (default: '')."""
    val, _ = resolve_setting_with_source("HELIOS_GIT_OWNER")
    return val


def get_git_token() -> str | None:
    """Resolve HELIOS_GIT_TOKEN dynamically (default: None)."""
    val, _ = resolve_setting_with_source("HELIOS_GIT_TOKEN")
    return val


def get_webhook_url() -> str:
    """Resolve HELIOS_WEBHOOK_URL dynamically (e.g. 'https://helios.example.com/webhook/git')."""
    val, _ = resolve_setting_with_source("HELIOS_WEBHOOK_URL")
    return val


# Module-level dynamic attribute lookups via PEP 562 (__getattr__) so both
# `from src.config import get_word_limit` and `config.HELIOS_WORD_LIMIT`
# evaluate layered resolution dynamically at runtime.
def __getattr__(name: str):
    if name == "MEMORY_DATA_DIR":
        return get_memory_data_dir()
    if name == "HELIOS_API_KEY":
        return get_api_key()
    if name == "HELIOS_WEBHOOK_SECRET":
        return get_webhook_secret()
    if name == "HELIOS_ALLOWED_ORIGINS":
        return get_allowed_origins()
    if name == "HELIOS_PUBLIC_URL":
        return get_public_url()
    if name in MUTABLE_SETTINGS:
        val, _ = resolve_setting_with_source(name)
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
