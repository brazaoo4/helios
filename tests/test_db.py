from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

import src.config as config
from src.db import (
    flag_stale_by_files,
    get_connection,
    init_db,
    list_aliases,
    migrate_scope,
    prune_expired_episodic,
    query_memories,
    remove_alias,
    resolve_scope,
    revalidate_memories,
    set_alias,
    upsert_memory,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """
    Runs automatically before every test:
    Points MEMORY_DATA_DIR to a temporary directory isolated to that test,
    then initializes a clean database.
    """
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HELIOS_WORD_LIMIT", raising=False)
    monkeypatch.delenv("HELIOS_EPISODIC_TTL_DAYS", raising=False)
    monkeypatch.delenv("HELIOS_CHANGELOG_LIMIT", raising=False)
    monkeypatch.delenv("HELIOS_API_KEY", raising=False)
    monkeypatch.delenv("HELIOS_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("HELIOS_ALLOWED_ORIGINS", raising=False)
    init_db()


# --- 2.0: Centralized Config & Environment Bounds ---

def test_config_defaults_and_dynamic_env(monkeypatch, tmp_path):
    assert config.MEMORY_DATA_DIR == Path(str(tmp_path))
    assert config.HELIOS_API_KEY is None
    assert config.HELIOS_WEBHOOK_SECRET is None
    assert config.HELIOS_WORD_LIMIT == 25
    assert config.HELIOS_EPISODIC_TTL_DAYS == 14
    assert config.HELIOS_CHANGELOG_LIMIT == 100
    assert config.HELIOS_ALLOWED_ORIGINS == ["*"]

    monkeypatch.setenv("HELIOS_API_KEY", "test-key-123")
    monkeypatch.setenv("HELIOS_WEBHOOK_SECRET", "hook-secret-456")
    monkeypatch.setenv("HELIOS_WORD_LIMIT", "40")
    monkeypatch.setenv("HELIOS_EPISODIC_TTL_DAYS", "7")
    monkeypatch.setenv("HELIOS_CHANGELOG_LIMIT", "50")
    monkeypatch.setenv("HELIOS_ALLOWED_ORIGINS", "https://app.example.com, http://localhost:3000")

    assert config.HELIOS_API_KEY == "test-key-123"
    assert config.HELIOS_WEBHOOK_SECRET == "hook-secret-456"
    assert config.HELIOS_WORD_LIMIT == 40
    assert config.HELIOS_EPISODIC_TTL_DAYS == 7
    assert config.HELIOS_CHANGELOG_LIMIT == 50
    assert config.HELIOS_ALLOWED_ORIGINS == ["https://app.example.com", "http://localhost:3000"]

    monkeypatch.setenv("HELIOS_WORD_LIMIT", "not-an-int")
    with pytest.raises(ValueError, match="must be an integer"):
        _ = config.HELIOS_WORD_LIMIT


# --- 2.1: Schema, PRAGMAs & Idempotency ---

def test_init_db_is_idempotent_and_sets_wal():
    # Calling init_db a second time must be a safe no-op
    init_db()

    with get_connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode == "wal"

        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view');"
            ).fetchall()
        }
        assert "memories" in tables
        assert "memories_fts" in tables
        assert "scope_aliases" in tables


# --- 2.2: Dynamic Scope Aliases & Fallback Normalization ---

@pytest.mark.parametrize(
    "raw_input, expected",
    [
        ("my_new_app", "my_new_app"),
        ("/opt/repos/Backend-Service", "backend-service"),
        (r"C:\Users\dev\Projects\Web-Portal\\", "web-portal"),
        ("https://github.com/org/core-engine.git", "core-engine"),
        ("helios", "helios"),
        ("", "global"),
        ("   ", "global"),
        ("custom_service", "custom_service"),
    ],
)
def test_resolve_scope_fallback_normalization(raw_input, expected):
    assert resolve_scope(raw_input) == expected


def test_dynamic_scope_aliases_crud():
    # Initially no hardcoded aliases exist
    assert list_aliases() == {}
    assert resolve_scope("frontend-v2") == "frontend-v2"

    # Set alias
    set_alias("frontend-v2", "web")
    set_alias("Infra-Repo", "infrastructure")
    assert list_aliases() == {"frontend-v2": "web", "infra-repo": "infrastructure"}

    # Resolve using dynamic alias (including path & .git variations)
    assert resolve_scope("frontend-v2") == "web"
    assert resolve_scope("/var/www/frontend-v2.git") == "web"
    assert resolve_scope(r"C:\repos\Infra-Repo\\") == "infrastructure"

    # Update existing alias
    set_alias("frontend-v2", "web-next")
    assert resolve_scope("frontend-v2") == "web-next"

    # Remove alias
    assert remove_alias("frontend-v2") is True
    assert remove_alias("frontend-v2") is False
    assert resolve_scope("frontend-v2") == "frontend-v2"
    assert list_aliases() == {"infra-repo": "infrastructure"}


# --- 2.3: TTL Pruning for Episodic Notes ---

def test_prune_expired_episodic(monkeypatch):
    now = datetime.now(timezone.utc)
    ts_15_days_ago = (now - timedelta(days=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_13_days_ago = (now - timedelta(days=13)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_20_days_ago = (now - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_connection() as conn:
        # 1. 15-day-old episodic memory -> should be archived
        conn.execute(
            """
            INSERT INTO memories (scope, category, content, status, valid_from, last_accessed)
            VALUES ('infrastructure', 'episodic', 'Old debug note', 'active', ?, ?)
            """,
            (ts_15_days_ago, ts_15_days_ago),
        )
        # 2. 13-day-old episodic memory -> should stay active
        conn.execute(
            """
            INSERT INTO memories (scope, category, content, status, valid_from, last_accessed)
            VALUES ('infrastructure', 'episodic', 'Recent debug note', 'active', ?, ?)
            """,
            (ts_13_days_ago, ts_13_days_ago),
        )
        # 3. 20-day-old fact -> should stay active (facts have infinite TTL)
        conn.execute(
            """
            INSERT INTO memories (scope, category, content, status, valid_from, last_accessed)
            VALUES ('infrastructure', 'fact', 'Permanent rule or fact', 'active', ?, ?)
            """,
            (ts_20_days_ago, ts_20_days_ago),
        )

    pruned = prune_expired_episodic()
    assert pruned == 1

    with get_connection() as conn:
        rows = conn.execute("SELECT content, status, valid_to FROM memories ORDER BY id").fetchall()

    assert rows[0]["status"] == "archived" and rows[0]["valid_to"] is not None
    assert rows[1]["status"] == "active" and rows[1]["valid_to"] is None
    assert rows[2]["status"] == "active" and rows[2]["valid_to"] is None

    # Configurable HELIOS_EPISODIC_TTL_DAYS (e.g. 10 days archives the 13-day-old episodic note)
    monkeypatch.setenv("HELIOS_EPISODIC_TTL_DAYS", "10")
    pruned_custom = prune_expired_episodic()
    assert pruned_custom == 1


# --- 2.4: AUDN Write Gate & Configurable Word Limit Boundaries ---

def test_upsert_validation_errors():
    with pytest.raises(ValueError, match="Invalid category"):
        upsert_memory("infrastructure", "invalid_cat", "Test note")

    with pytest.raises(ValueError, match="cannot be empty"):
        upsert_memory("infrastructure", "fact", "   ")

    with pytest.raises(ValueError, match="exceeds 25-word limit"):
        long_content = " ".join(["word"] * 26)
        upsert_memory("infrastructure", "fact", long_content)


def test_upsert_configurable_word_limit_boundaries(monkeypatch):
    # Lower word limit to 10
    monkeypatch.setenv("HELIOS_WORD_LIMIT", "10")

    # Exactly 10 words succeeds
    ten_words = " ".join(["token"] * 10)
    res_ok = upsert_memory("webapp", "fact", ten_words, subject="ten-words")
    assert res_ok["action"] == "created"

    # 11 words fails with dynamic 10-word limit message
    eleven_words = " ".join(["token"] * 11)
    with pytest.raises(ValueError, match="exceeds 10-word limit"):
        upsert_memory("webapp", "fact", eleven_words, subject="eleven-words")

    # Raise word limit to 35
    monkeypatch.setenv("HELIOS_WORD_LIMIT", "35")
    thirty_words = " ".join(["token"] * 30)
    res_thirty = upsert_memory("webapp", "fact", thirty_words, subject="thirty-words")
    assert res_thirty["action"] == "created"


def test_upsert_duplicate_noop():
    res1 = upsert_memory("infrastructure", "fact", "Media server on port 8096", subject="media-port")
    assert res1["action"] == "created"

    res2 = upsert_memory("infrastructure", "fact", "Media server on port 8096", subject="media-port")
    assert res2["action"] == "no-op (verified existing)"
    assert res2["id"] == res1["id"]

    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        assert count == 1


def test_upsert_slot_supersession():
    res1 = upsert_memory("infrastructure", "fact", "Service port is 8096", subject="svc-port")
    res2 = upsert_memory("infrastructure", "fact", "Service port is 8097", subject="svc-port")

    assert res2["action"] == "superseded"
    assert res2["superseded_ids"] == [res1["id"]]

    with get_connection() as conn:
        old_row = conn.execute("SELECT status, valid_to, superseded_by FROM memories WHERE id = ?", (res1["id"],)).fetchone()
        new_row = conn.execute("SELECT status, valid_to, superseded_by FROM memories WHERE id = ?", (res2["id"],)).fetchone()

    assert old_row["status"] == "superseded"
    assert old_row["valid_to"] is not None
    assert old_row["superseded_by"] == res2["id"]
    assert new_row["status"] == "active"
    assert new_row["valid_to"] is None


def test_upsert_explicit_replaces_id():
    res1 = upsert_memory("infrastructure", "fact", "First draft of rule")
    res2 = upsert_memory("infrastructure", "fact", "Second revised rule", replaces_id=res1["id"])

    assert res2["action"] == "superseded"
    assert res2["superseded_ids"] == [res1["id"]]

    with pytest.raises(ValueError, match="does not exist or is already superseded"):
        upsert_memory("infrastructure", "fact", "Third rule", replaces_id=9999)


# --- 2.5: FTS5 Search & Categorical Fallback ---

def test_query_memories_keyword_and_sanitization():
    upsert_memory("infrastructure", "fact", "Metrics agent at 172.16.1.150:8090", subject="metrics")
    upsert_memory("infrastructure", "fact", "Storage pool has minfreespace 100G on disk1", subject="storage")

    # Keyword search
    res = query_memories("infrastructure", "metrics")
    assert len(res) == 1
    assert res[0]["subject"] == "metrics"

    # Search with IP, dots, and colons (single-digit '1' must not match '100G' / 'disk1')
    res_ip = query_memories("infrastructure", "172.16.1.150:8090")
    assert len(res_ip) == 1
    assert res_ip[0]["subject"] == "metrics"

    # Malformed / punctuation queries must not crash
    assert query_memories("infrastructure", '"*( AND :') == []
    assert query_memories("infrastructure", "!@#$%^&*") == []


def test_query_memories_empty_query_priority():
    upsert_memory("infrastructure", "preference", "Prefer dark mode")
    upsert_memory("global", "rule", "Always keep commands concise")
    upsert_memory("infrastructure", "fact", "Postgres runs on port 5432")

    results = query_memories("infrastructure", "")
    assert len(results) == 3
    # Rule must come first regardless of insertion order
    assert results[0]["category"] == "rule"
    assert results[1]["category"] == "fact"
    assert results[2]["category"] == "preference"


def test_query_excludes_superseded_and_tracks_hits():
    res1 = upsert_memory("infrastructure", "fact", "Old port was 7070", subject="port")
    upsert_memory("infrastructure", "fact", "New port is 7071", subject="port")

    # Old memory must not be retrieved
    assert query_memories("infrastructure", "7070") == []

    # Active memory query increments hit_count
    match = query_memories("infrastructure", "7071")
    assert len(match) == 1

    with get_connection() as conn:
        row = conn.execute("SELECT hit_count FROM memories WHERE content LIKE '%7071%'").fetchone()
        assert row["hit_count"] >= 1


# --- 2.6: Drift Flagging ---

def test_flag_stale_by_files():
    set_alias("Infra-Repo", "infrastructure")
    upsert_memory(
        "Infra-Repo",
        "fact",
        "Metrics agent requires RAWIO",
        subject="metrics-caps",
        anchor_files=["stacks/monitoring/compose.yaml"],
    )

    # Negative check: non-matching file
    flagged = flag_stale_by_files("infrastructure", ["stacks/core/compose.yaml"], "sha111")
    assert flagged == 0

    # Positive check: matching anchor
    flagged = flag_stale_by_files("infrastructure", ["stacks/monitoring/compose.yaml"], "sha222")
    assert flagged == 1

    memories = query_memories("infrastructure", "Metrics")
    assert len(memories) == 1
    assert memories[0]["status"] == "stale"
    assert "sha222" in memories[0]["stale_reason"]

    # Repeat call on already stale row does not re-flag
    assert flag_stale_by_files("infrastructure", ["stacks/monitoring/compose.yaml"], "sha222") == 0


# --- 2.7: Scope Migration & Collision Resolution ---

def test_migrate_scope_validation():
    with pytest.raises(ValueError, match="Source scope cannot be empty"):
        migrate_scope("", "ticketera")
    with pytest.raises(ValueError, match="Target scope cannot be empty"):
        migrate_scope("ticket-tracker", "")
    with pytest.raises(ValueError, match="cannot be identical"):
        migrate_scope("ticketera", "ticketera")


def test_migrate_scope_basic_and_aliases():
    # Insert memories into source scope
    upsert_memory("ticket-tracker", "fact", "Port 8000 used by web", subject="port")
    upsert_memory("ticket-tracker", "rule", "Always run migrations")

    # Add an alias pointing to source scope
    set_alias("legacy-tickets", "ticket-tracker")

    res = migrate_scope("ticket-tracker", "ticketera", register_alias=True)
    assert res["from_scope"] == "ticket-tracker"
    assert res["to_scope"] == "ticketera"
    assert res["migrated_count"] == 2
    assert res["alias_registered"] is True

    # Memories now belong to target scope
    recalled = query_memories("ticketera", "")
    assert len(recalled) == 2
    for m in recalled:
        assert m["scope"] == "ticketera"

    # Alias table has ticket-tracker -> ticketera and legacy-tickets repointed to ticketera
    aliases = list_aliases()
    assert aliases["ticket-tracker"] == "ticketera"
    assert aliases["legacy-tickets"] == "ticketera"


def test_migrate_scope_slot_collision_resolution():
    # from_scope has an older memory with subject 'db-host'
    m1 = upsert_memory("old-proj", "fact", "DB host is postgres-old", subject="db-host")
    # to_scope has a newer memory with same subject 'db-host'
    m2 = upsert_memory("new-proj", "fact", "DB host is postgres-new", subject="db-host")

    # Migrate old-proj into new-proj; m1 must be superseded by m2
    res = migrate_scope("old-proj", "new-proj", register_alias=True)
    assert res["migrated_count"] >= 1

    # Only 1 active memory for 'db-host' in new-proj
    active_mems = query_memories("new-proj", "postgres", status_filter="active")
    assert len(active_mems) == 1
    assert active_mems[0]["id"] == m2["id"]
    assert "postgres-new" in active_mems[0]["content"]

    # Verify m1 is superseded by m2 in SQLite
    with get_connection() as conn:
        row1 = conn.execute("SELECT status, valid_to, superseded_by, scope FROM memories WHERE id = ?", (m1["id"],)).fetchone()
        assert row1["status"] == "superseded"
        assert row1["valid_to"] is not None
        assert row1["superseded_by"] == m2["id"]
        assert row1["scope"] == "new-proj"


def test_cross_scope_replaces_id_with_alias():
    # 1. Create a memory in old scope
    m1 = upsert_memory("ticket-tracker", "fact", "Old API version 1.0", subject="api-ver")

    # 2. Cross-scope replacement without alias must fail
    with pytest.raises(ValueError, match="Cannot supersede memory across different scopes"):
        upsert_memory("ticketera", "fact", "New API version 2.0", subject="api-ver", replaces_id=m1["id"])

    # 3. Create alias ticket-tracker -> ticketera
    set_alias("ticket-tracker", "ticketera")

    # 4. Now replaces_id should succeed seamlessly
    m2 = upsert_memory("ticketera", "fact", "New API version 2.0", subject="api-ver", replaces_id=m1["id"])
    assert m2["action"] == "superseded"
    assert m1["id"] in m2["superseded_ids"]

    # Old memory should be superseded by new memory
    with get_connection() as conn:
        row1 = conn.execute("SELECT status, superseded_by FROM memories WHERE id = ?", (m1["id"],)).fetchone()
        assert row1["status"] == "superseded"
        assert row1["superseded_by"] == m2["id"]


# --- 2.8: Batch Stale Memory Revalidation ---

def test_revalidate_memories_db():
    m1 = upsert_memory("infra", "fact", "Service runs on port 9090", anchor_files=["app.py"])
    m2 = upsert_memory("infra", "fact", "Worker runs on port 9091", anchor_files=["worker.py"])

    # Flag both as stale
    flag_stale_by_files("infra", ["app.py", "worker.py"], "sha555")

    stale_mems = query_memories("infra", "", status_filter="stale")
    assert len(stale_mems) == 2

    # Batch revalidate m1 and a nonexistent ID 99999
    res = revalidate_memories([m1["id"], 99999])
    assert res["revalidated_ids"] == [m1["id"]]
    assert res["not_found_or_not_stale_ids"] == [99999]

    # m1 is active, m2 is still stale
    with get_connection() as conn:
        row1 = conn.execute("SELECT status, stale_reason FROM memories WHERE id = ?", (m1["id"],)).fetchone()
        assert row1["status"] == "active"
        assert row1["stale_reason"] == ""

        row2 = conn.execute("SELECT status FROM memories WHERE id = ?", (m2["id"],)).fetchone()
        assert row2["status"] == "stale"


# --- 2.9: Query Filtering (Category, Status) and Token Preservation ---

def test_query_memories_category_and_status_filtering():
    upsert_memory("proj", "rule", "Rule 1: Always write tests", subject="testing")
    upsert_memory("proj", "fact", "Fact 1: Redis port 6379", subject="redis", anchor_files=["compose.yaml"])
    upsert_memory("proj", "preference", "Pref 1: Tab size 4")

    # Flag redis as stale
    flag_stale_by_files("proj", ["compose.yaml"], "sha999")

    # Filter by category="rule"
    rules = query_memories("proj", "", category="rule")
    assert len(rules) == 1
    assert rules[0]["category"] == "rule"

    # Filter by status="stale"
    stales = query_memories("proj", "", status_filter="stale")
    assert len(stales) == 1
    assert stales[0]["status"] == "stale"
    assert stales[0]["category"] == "fact"

    # Filter by category="rule" AND status="stale" -> empty
    none_stale_rules = query_memories("proj", "", category="rule", status_filter="stale")
    assert len(none_stale_rules) == 0

    # Filter by category="fact" AND status="stale" in FTS match
    fts_stale = query_memories("proj", "Redis", category="fact", status_filter="stale")
    assert len(fts_stale) == 1
    assert fts_stale[0]["subject"] == "redis"

    # Filter by status="active"
    actives = query_memories("proj", "", status_filter="active")
    assert len(actives) == 2
    assert all(a["status"] == "active" for a in actives)


def test_query_memories_technical_tokens():
    upsert_memory("infra", "fact", "Cluster IP is 192.168.1.150:8000 in compose.yaml at v0.1.0", subject="cluster")

    # Search for full technical token with dot and colon
    res_ip = query_memories("infra", "192.168.1.150:8000")
    assert len(res_ip) == 1
    assert res_ip[0]["subject"] == "cluster"

    # Search for compose.yaml
    res_compose = query_memories("infra", "compose.yaml")
    assert len(res_compose) == 1

    # Search for v0.1.0
    res_ver = query_memories("infra", "v0.1.0")
    assert len(res_ver) == 1

    # Query with boolean operators and quotes should not throw sqlite3.OperationalError
    res_bool = query_memories("infra", 'AND NOT "compose.yaml"')
    assert len(res_bool) == 1
