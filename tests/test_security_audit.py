"""Security regression tests verifying all white-box audit remediations (HEL-01 to HEL-14)."""

import io
import sqlite3
import tarfile
import pytest
from starlette.testclient import TestClient

from src.config import (
    LOCKED_SECURITY_KEYS,
    get_allowed_origins,
    validate_http_url,
    validate_setting_value,
)
from src.db import (
    db_prune_memories,
    flag_stale_by_files,
    get_connection,
    list_aliases,
    revalidate_memories,
    set_alias,
    set_runtime_setting,
    upsert_memory,
)
from src.db.search import build_fts5_query
from src.exporter import create_portable_archive
from src.middleware.auth import _constant_time_equals
from src.onboarding import (
    escape_bash_single_quote,
    escape_ps_single_quote,
    generate_setup_bash,
    generate_setup_powershell,
    generate_uninstall_bash,
    generate_uninstall_powershell,
    validate_onboarding_params,
)
from src.server import app
from src.tools.config import manage_server_config


# --- HEL-01: Shell / PowerShell Injection Prevention ---

def test_hel01_onboarding_param_validation():
    with pytest.raises(ValueError, match="Invalid instance_role"):
        validate_onboarding_params(instance_role="'; calc.exe; '")

    with pytest.raises(ValueError, match="Invalid client"):
        validate_onboarding_params(client="$(reboot)")

    with pytest.raises(ValueError, match="Invalid instance_role"):
        generate_setup_bash("https://helios.example.com", instance_role="attacker-role")

    with pytest.raises(ValueError, match="Invalid client"):
        generate_setup_powershell("https://helios.example.com", client="bad-client")

    with pytest.raises(ValueError, match="Invalid client"):
        generate_uninstall_bash("https://helios.example.com", client="bad-client")

    with pytest.raises(ValueError, match="Invalid client"):
        generate_uninstall_powershell("https://helios.example.com", client="bad-client")


def test_hel01_escaping_helpers():
    assert escape_bash_single_quote("foo'bar") == "foo'\\''bar"
    assert escape_ps_single_quote("foo'bar") == "foo''bar"


def test_hel01_http_setup_endpoints_reject_malicious_params():
    with TestClient(app) as client:
        res_sh = client.get("/setup.sh?role=invalid-role")
        assert res_sh.status_code == 400
        assert "Invalid instance_role" in res_sh.text

        res_ps = client.get("/setup.ps1?client=invalid-client")
        assert res_ps.status_code == 400
        assert "Invalid client" in res_ps.text

        res_un_sh = client.get("/uninstall.sh?client=invalid-client")
        assert res_un_sh.status_code == 400
        assert "Invalid client" in res_un_sh.text

        res_un_ps = client.get("/uninstall.ps1?client=invalid-client")
        assert res_un_ps.status_code == 400
        assert "Invalid client" in res_un_ps.text


# --- HEL-02: Dynamic CORS Origins ---

def test_hel02_dynamic_cors_origin_handling(monkeypatch):
    monkeypatch.setenv("HELIOS_ALLOWED_ORIGINS", "https://allowed.example.com")
    with TestClient(app) as client:
        # Allowed origin receives CORS header
        res = client.get("/health", headers={"Origin": "https://allowed.example.com"})
        assert res.headers.get("access-control-allow-origin") == "https://allowed.example.com"

        # Disallowed origin does not receive CORS header
        res_evil = client.get("/health", headers={"Origin": "https://attacker.evil.com"})
        assert "access-control-allow-origin" not in res_evil.headers


# --- HEL-03: SSRF Protection & URL Validation ---

def test_hel03_ssrf_url_validation_blocks_private_and_metadata_ips():
    forbidden_urls = [
        "http://169.254.169.254/latest/meta-data",
        "http://100.100.100.200/metadata",
        "http://[::ffff:169.254.169.254]/",
        "http://127.0.0.1:8000/",
        "http://0.0.0.0:8000/",
        "http://localhost/api",
        "http://foo.localhost/api",
        "http://2130706433/",  # Decimal representation of 127.0.0.1
        "http://0x7f000001/",  # Hex representation of 127.0.0.1
        "http://user:pass@git.example.com/api",  # Credentials in URL
        "http://git.example.com/api;echo 1",  # Command injection characters
        "http://git.example.com/api$(whoami)",
    ]
    for url in forbidden_urls:
        with pytest.raises(ValueError):
            validate_http_url(url, allow_loopback=False)


# --- HEL-04: Constant Time Hash Comparison ---

def test_hel04_constant_time_equals_prehash():
    assert _constant_time_equals("secret-token", "secret-token") is True
    assert _constant_time_equals("secret-token", "wrong-token") is False
    assert _constant_time_equals(None, "secret-token") is False
    assert _constant_time_equals("secret-token", None) is False
    assert _constant_time_equals(None, None) is True
    # Different lengths
    assert _constant_time_equals("a", "aaaaaaaaaaaaaaaa") is False


# --- HEL-05: Request Body Limiting (413 Payload Too Large) ---

def test_hel05_body_size_limit(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "test-auth-key")
    with TestClient(app) as client:
        # Body larger than 1MB (1048576 bytes)
        large_body = b"x" * (1024 * 1024 + 10)
        res = client.post(
            "/messages",
            content=large_body,
            headers={
                "Authorization": "Bearer test-auth-key",
                "Content-Type": "application/json",
            },
        )
        assert res.status_code == 413


# --- HEL-06: Strict POST /messages Authentication ---

def test_hel06_post_messages_requires_auth(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "test-auth-key")
    with TestClient(app) as client:
        # Unauthenticated request with fake session_id must fail 401
        res = client.post("/messages?session_id=fake-session", json={"type": "ping"})
        assert res.status_code == 401


# --- HEL-08: FTS5 Query Injection Hardening ---

def test_hel08_fts5_query_injection_sanitization():
    query = build_fts5_query(['foo"', "bar*", "baz\x00qux", 'test""inject'])
    assert "\x00" not in query
    # Double quotes are escaped properly as ""
    assert '""' in query
    # Large token list is truncated to 32
    many_tokens = [f"tok{i}" for i in range(50)]
    query_many = build_fts5_query(many_tokens)
    assert len(query_many.split(" OR ")) <= 32


# --- HEL-09: AUDN Write Gate Unicode Normalization ---

def test_hel09_write_gate_invisible_characters():
    # Content with zero-width spaces (\u200b) and soft hyphens (\u00ad)
    invisible_content = "This\u200bis\u00ada\u200btest\u200bmemory."
    mem = upsert_memory(
        raw_scope="test-sec",
        category="fact",
        content=invisible_content,
        subject="unicode-test",
    )
    assert mem["id"] > 0
    with get_connection() as conn:
        row = conn.execute("SELECT content FROM memories WHERE id = ?", (mem["id"],)).fetchone()
        assert "\u200b" not in row["content"]
        assert "\u00ad" not in row["content"]


# --- HEL-10: Subject and Anchor File Validation ---

def test_hel10_subject_and_anchor_file_validation():
    with pytest.raises(ValueError, match="must not contain brackets"):
        upsert_memory(
            raw_scope="test-sec",
            category="fact",
            content="Valid atomic content fact.",
            subject="invalid[subject]`with`brackets",
        )

    with pytest.raises(ValueError, match="without backticks or newlines"):
        upsert_memory(
            raw_scope="test-sec",
            category="fact",
            content="Valid atomic content fact.",
            subject="valid-subject",
            anchor_files=["src/test.py`evil`"],
        )


# --- HEL-11: Stale Timestamp & Prune Retention ---

def test_hel11_stale_since_column_and_prune_logic():
    mem = upsert_memory(
        raw_scope="stale-test",
        category="fact",
        content="A fact that will be flagged stale.",
        subject="stale-subj",
        anchor_files=["src/module.py"],
    )
    mem_id = mem["id"]

    # Flag stale
    count = flag_stale_by_files("stale-test", ["src/module.py"], "abcdef123456")
    assert count >= 1

    with get_connection() as conn:
        row = conn.execute("SELECT status, stale_since FROM memories WHERE id = ?", (mem_id,)).fetchone()
        assert row["status"] == "stale"
        assert row["stale_since"] is not None

    # Revalidate clears stale_since
    revalidate_memories([mem_id])
    with get_connection() as conn:
        row = conn.execute("SELECT status, stale_since FROM memories WHERE id = ?", (mem_id,)).fetchone()
        assert row["status"] == "active"
        assert row["stale_since"] is None


# --- HEL-12: Scope Alias Traversal & Cycle Protection ---

def test_hel12_scope_alias_hardening():
    with pytest.raises(ValueError, match="reserved 'global' scope"):
        set_alias("my-project", "global")

    with pytest.raises(ValueError, match="cannot be identical"):
        set_alias("my-project", "my-project")

    with pytest.raises(ValueError, match="Alias cannot be empty"):
        set_alias("..", "target")

    with pytest.raises(ValueError, match="Canonical scope cannot be empty"):
        set_alias("valid-alias", "..")


# --- HEL-13: Portable Archive Secret Redaction ---

def test_hel13_portable_archive_redacts_secrets(tmp_path):
    set_runtime_setting("HELIOS_GIT_TOKEN", "sensitive-runtime-token")
    set_runtime_setting("HELIOS_WORD_LIMIT", "30")

    archive_path = create_portable_archive()
    with tarfile.open(archive_path, "r:gz") as tar:
        # Extract memory.db from tar bundle
        member = tar.getmember("memory.db")
        f = tar.extractfile(member)
        assert f is not None
        db_bytes = f.read()
        tmp_db = tmp_path / "restored.db"
        tmp_db.write_bytes(db_bytes)

        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        rows = dict(cursor.execute("SELECT key, value FROM runtime_settings").fetchall())
        conn.close()

        # Sensitive token MUST NOT be present in export
        assert "HELIOS_GIT_TOKEN" not in rows
        # Non-sensitive settings remain
        assert rows.get("HELIOS_WORD_LIMIT") == "30"


# --- HEL-14: Runtime Git Token Invalidation on URL Change ---

def test_hel14_runtime_git_token_invalidation():
    # Set runtime token
    manage_server_config(action="set", key="HELIOS_GIT_TOKEN", value="temp-pat-123")
    res_list = manage_server_config(action="list")
    assert "•••••••• (configured)" in res_list

    # Change GIT API URL
    res_set = manage_server_config(action="set", key="HELIOS_GIT_API_URL", value="https://new-git.mesh.lan/api")
    assert "Invalidated for safety" in res_set or "invalidated for safety" in res_set

    # Verify runtime token is cleared
    res_list_after = manage_server_config(action="list")
    assert "(unset)" in res_list_after
