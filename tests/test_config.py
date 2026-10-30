"""Unit tests for src.config layered settings, URL sanitization, and runtime overrides."""

import pytest

from src.config import (
    get_allowed_origins,
    get_memory_data_dir,
    get_word_limit,
    resolve_setting_with_source,
    validate_http_url,
    validate_setting_value,
)
from src.db import set_runtime_setting


def test_validate_http_url():
    # 1. Empty URL
    assert validate_http_url("") == ""
    assert validate_http_url("   ") == ""

    # 2. Valid HTTP / HTTPS URLs
    assert validate_http_url("https://helios.example.com/api/") == "https://helios.example.com/api"
    assert validate_http_url("http://192.168.1.50:8000") == "http://192.168.1.50:8000"

    # 3. Invalid characters
    with pytest.raises(ValueError, match="invalid characters"):
        validate_http_url("https://example.com/path with spaces")
    with pytest.raises(ValueError, match="invalid characters"):
        validate_http_url('https://example.com/"quoted"')

    # 4. Invalid schemes
    with pytest.raises(ValueError, match="URL scheme must be http or https"):
        validate_http_url("ftp://example.com")

    # 5. Missing host
    with pytest.raises(ValueError, match="valid host"):
        validate_http_url("http://")

    # 6. Credentials forbidden
    with pytest.raises(ValueError, match="embedded user credentials"):
        validate_http_url("https://user:pass@example.com")

    # 7. Fragments forbidden
    with pytest.raises(ValueError, match="URL fragment"):
        validate_http_url("https://example.com/path#fragment")

    # 8. Cloud metadata forbidden
    with pytest.raises(ValueError, match="cloud metadata"):
        validate_http_url("http://metadata.google.internal")
    with pytest.raises(ValueError, match="cloud metadata"):
        validate_http_url("http://169.254.169.254/latest/meta-data")

    # 9. Loopback rules
    with pytest.raises(ValueError, match="Loopback"):
        validate_http_url("http://127.0.0.1:8000", allow_loopback=False)
    with pytest.raises(ValueError, match="Loopback"):
        validate_http_url("http://localhost:8000", allow_loopback=False)

    assert validate_http_url("http://localhost:8000", allow_loopback=True) == "http://localhost:8000"
    assert validate_http_url("http://127.0.0.1:8000", allow_loopback=True) == "http://127.0.0.1:8000"


def test_validate_setting_value():
    # 1. Locked settings raise ValueError
    with pytest.raises(ValueError, match="locked"):
        validate_setting_value("HELIOS_API_KEY", "secret")

    # 2. Unknown setting raises KeyError
    with pytest.raises(KeyError, match="Unknown setting"):
        validate_setting_value("TOTALLY_UNKNOWN", "value")

    # 3. Integer validation
    assert validate_setting_value("HELIOS_WORD_LIMIT", "30") == 30
    with pytest.raises(ValueError, match="must be an integer"):
        validate_setting_value("HELIOS_WORD_LIMIT", "not-a-number")
    with pytest.raises(ValueError, match="must be between"):
        validate_setting_value("HELIOS_WORD_LIMIT", 2)
    with pytest.raises(ValueError, match="must be between"):
        validate_setting_value("HELIOS_WORD_LIMIT", 500)

    # 4. Git token normalization
    assert validate_setting_value("HELIOS_GIT_TOKEN", None) is None
    assert validate_setting_value("HELIOS_GIT_TOKEN", "  my-pat  ") == "my-pat"
    assert validate_setting_value("HELIOS_GIT_TOKEN", "") is None

    # 5. Public URL validation
    assert (
        validate_setting_value("HELIOS_PUBLIC_URL", "https://public.mesh:8443/")
        == "https://public.mesh:8443"
    )


def test_resolve_setting_with_source(monkeypatch):
    # 1. Unknown key raises KeyError
    with pytest.raises(KeyError, match="Unknown setting"):
        resolve_setting_with_source("UNKNOWN_KEY")

    # 2. Defaults when nothing is set
    val, src = resolve_setting_with_source("HELIOS_WORD_LIMIT")
    assert val == 25
    assert src == "default"

    # 3. Environment variable override
    monkeypatch.setenv("HELIOS_WORD_LIMIT", "40")
    val_env, src_env = resolve_setting_with_source("HELIOS_WORD_LIMIT")
    assert val_env == 40
    assert src_env == "env"

    # 4. Invalid env variable errors
    monkeypatch.setenv("HELIOS_WORD_LIMIT", "invalid-int")
    with pytest.raises(ValueError, match="must be an integer"):
        resolve_setting_with_source("HELIOS_WORD_LIMIT")

    monkeypatch.setenv("HELIOS_WORD_LIMIT", "0")
    with pytest.raises(ValueError, match="must be >= 1"):
        resolve_setting_with_source("HELIOS_WORD_LIMIT")

    monkeypatch.setenv("HELIOS_WORD_LIMIT", "3")
    with pytest.raises(ValueError, match="must be >= 5"):
        resolve_setting_with_source("HELIOS_WORD_LIMIT")

    monkeypatch.setenv("HELIOS_WORD_LIMIT", "300")
    with pytest.raises(ValueError, match="must be <= 200"):
        resolve_setting_with_source("HELIOS_WORD_LIMIT")

    # 5. Invalid git provider env variable
    monkeypatch.setenv("HELIOS_GIT_PROVIDER", "unsupported_provider")
    with pytest.raises(ValueError, match="must be one of"):
        resolve_setting_with_source("HELIOS_GIT_PROVIDER")

    # 6. Database override takes precedence over environment variable
    monkeypatch.setenv("HELIOS_WORD_LIMIT", "50")
    set_runtime_setting("HELIOS_WORD_LIMIT", "60")
    val_db, src_db = resolve_setting_with_source("HELIOS_WORD_LIMIT")
    assert val_db == 60
    assert src_db == "db"

    # 7. Corrupted DB setting gracefully falls back to env/default
    set_runtime_setting("HELIOS_WORD_LIMIT", "corrupted-value")
    val_fallback, src_fallback = resolve_setting_with_source("HELIOS_WORD_LIMIT")
    assert val_fallback == 50
    assert src_fallback == "env"


def test_helper_getters(monkeypatch, tmp_path):
    # Word limit helper
    assert get_word_limit() == 25
    monkeypatch.setenv("HELIOS_WORD_LIMIT", "35")
    assert get_word_limit() == 35

    # Allowed origins helper
    monkeypatch.setenv("HELIOS_ALLOWED_ORIGINS", "https://a.com, https://b.com")
    origins = get_allowed_origins()
    assert origins == ["https://a.com", "https://b.com"]

    # Memory data dir helper
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path / "custom_data"))
    data_dir = get_memory_data_dir()
    assert data_dir == tmp_path / "custom_data"
