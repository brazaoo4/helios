import json
import pytest
from unittest.mock import patch

from src.db import get_connection, init_db, query_memories, resolve_scope, set_alias, upsert_memory
from src.seed import (
    INITIAL_FACTS,
    clear_memories,
    ingest_declarative_seed_files,
    is_db_empty,
    main,
    seed,
    seed_if_empty,
    validate_facts,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Isolate each test in a clean temporary data directory."""
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path))
    init_db()


def test_initial_facts_comply_with_all_invariants():
    """Verify that every fact in INITIAL_FACTS is fully valid and strictly <= 25 words."""
    errors = validate_facts(INITIAL_FACTS)
    assert errors == [], f"Validation errors found in INITIAL_FACTS: {errors}"


def test_validate_facts_detects_errors():
    """Verify validate_facts catches missing keys, long content, and duplicate slots."""
    # 1. Missing keys
    assert any("missing required field" in e for e in validate_facts([{"scope": "global"}]))

    # 2. Invalid category
    bad_cat = [
        {
            "scope": "global",
            "category": "not-a-category",
            "subject": "sub",
            "content": "Short valid text.",
            "anchor_files": [],
        }
    ]
    assert any("invalid category" in e for e in validate_facts(bad_cat))

    # 3. Exceeding 25 words
    long_content = [
        {
            "scope": "global",
            "category": "rule",
            "subject": "too-long",
            "content": " ".join(["word"] * 26),
            "anchor_files": [],
        }
    ]
    assert any("exceeds 25-word limit" in e for e in validate_facts(long_content))

    # 4. Duplicate (scope, subject)
    dup_slots = [
        {
            "scope": "global",
            "category": "rule",
            "subject": "dup-slot",
            "content": "First valid fact.",
            "anchor_files": [],
        },
        {
            "scope": "global",
            "category": "rule",
            "subject": "dup-slot",
            "content": "Second fact with same slot.",
            "anchor_files": [],
        },
    ]
    assert any("duplicate (scope, subject) slot" in e for e in validate_facts(dup_slots))


def test_seed_basic_and_idempotency():
    """Verify that seed() creates memories on first run and no-ops on second run."""
    sample_facts = [
        {
            "scope": "infrastructure",
            "category": "fact",
            "subject": "test-fact-1",
            "content": "First test fact content.",
            "anchor_files": ["file1.txt"],
        },
        {
            "scope": "webapp",
            "category": "fact",
            "subject": "test-fact-2",
            "content": "Second test fact content.",
            "anchor_files": [],
        },
    ]

    res1 = seed(facts=sample_facts, verbose=False)
    assert res1["total_evaluated"] == 2
    assert res1["created"] == 2
    assert res1["no_op"] == 0
    assert len(res1["exports"]) >= 2

    # Verify rows in DB
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()[0]
        assert count == 2

    # Second run should be complete no-op
    res2 = seed(facts=sample_facts, verbose=False)
    assert res2["total_evaluated"] == 2
    assert res2["created"] == 0
    assert res2["no_op"] == 2


def test_seed_scope_filtering():
    """Verify scope_filter only seeds facts belonging to the matching scope."""
    sample_facts = [
        {
            "scope": "infrastructure",
            "category": "fact",
            "subject": "infra-1",
            "content": "Infrastructure fact content.",
            "anchor_files": [],
        },
        {
            "scope": "webapp",
            "category": "fact",
            "subject": "web-1",
            "content": "Webapp fact content.",
            "anchor_files": [],
        },
    ]

    res = seed(facts=sample_facts, scope_filter="infrastructure", verbose=False)
    assert res["total_evaluated"] == 1
    assert res["created"] == 1
    assert res["results"][0]["scope"] == "infrastructure"

    with get_connection() as conn:
        rows = conn.execute("SELECT scope FROM memories WHERE status = 'active'").fetchall()
        assert len(rows) == 1
        assert rows[0]["scope"] == "infrastructure"


def test_seed_dry_run_does_not_modify_db():
    """Verify that dry_run simulates actions without writing to SQLite."""
    sample_facts = [
        {
            "scope": "infrastructure",
            "category": "fact",
            "subject": "dry-run-subj",
            "content": "Dry run fact content.",
            "anchor_files": [],
        }
    ]

    res = seed(facts=sample_facts, dry_run=True, verbose=False)
    assert res["total_evaluated"] == 1
    assert res["results"][0]["action"] == "simulated"

    # Ensure DB remains empty
    assert is_db_empty() is True


def test_seed_if_empty():
    """Verify seed_if_empty seeds once and ignores subsequent calls."""
    sample_facts = [
        {
            "scope": "infrastructure",
            "category": "fact",
            "subject": "seed-empty-test",
            "content": "Seed if empty test content.",
            "anchor_files": [],
        }
    ]

    # First run when empty: should seed
    res1 = seed_if_empty(facts=sample_facts, verbose=False)
    assert res1 is not None
    assert res1["created"] == 1

    # Second run when populated: should return None
    res2 = seed_if_empty(facts=sample_facts, verbose=False)
    assert res2 is None


def test_clear_memories():
    """Verify clear_memories wipes all or scoped memories."""
    sample_facts = [
        {
            "scope": "infrastructure",
            "category": "fact",
            "subject": "sub-1",
            "content": "Fact one.",
            "anchor_files": [],
        },
        {
            "scope": "helios",
            "category": "fact",
            "subject": "sub-2",
            "content": "Fact two.",
            "anchor_files": [],
        },
    ]
    seed(facts=sample_facts, verbose=False)

    # Scoped clear
    deleted = clear_memories(scope_filter="infrastructure")
    assert deleted == 1

    with get_connection() as conn:
        scopes = [r[0] for r in conn.execute("SELECT scope FROM memories").fetchall()]
        assert scopes == ["helios"]

    # Global clear
    deleted_all = clear_memories()
    assert deleted_all == 1
    assert is_db_empty() is True


def test_cli_flags(capsys):
    """Test CLI commands (--check, --dry-run, --json, --if-empty)."""
    # 1. Test --check
    with patch("sys.argv", ["seed.py", "--check"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Validation PASSED" in captured.out

    # 2. Test --dry-run --json
    with patch("sys.argv", ["seed.py", "--dry-run", "--json", "--scope", "helios"]):
        main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_evaluated"] >= 1
        assert data["results"][0]["action"] == "simulated"


def test_ingest_declarative_seed_files_yaml_and_json(tmp_path):
    """Verify declarative seed.yaml and seed.json ingestion and atomic rename to .imported."""
    yaml_content = """
aliases:
  frontend-v2: web
memories:
  - scope: frontend-v2
    category: fact
    subject: framework
    content: Frontend uses Next.js 15 App Router on port 3000.
    anchor_files:
      - package.json
"""
    seed_yaml = tmp_path / "seed.yaml"
    seed_yaml.write_text(yaml_content, encoding="utf-8")

    ingested = ingest_declarative_seed_files(tmp_path)
    assert ingested == 1
    assert not seed_yaml.exists()
    assert (tmp_path / "seed.yaml.imported").exists()
    assert resolve_scope("frontend-v2") == "web"

    results = query_memories("web", "Next.js")
    assert len(results) == 1
    assert results[0]["subject"] == "framework"
    assert (tmp_path / "exports" / "web.md").exists()

    # Also test seed.json list format
    json_items = [
        {
            "scope": "api",
            "category": "rule",
            "subject": "auth-check",
            "content": "All API routes must verify Bearer JWT tokens.",
            "anchor_files": ["src/auth.py"],
        }
    ]
    seed_json = tmp_path / "seed.json"
    seed_json.write_text(json.dumps(json_items), encoding="utf-8")

    ingested_json = ingest_declarative_seed_files(tmp_path)
    assert ingested_json == 1
    assert not seed_json.exists()
    assert (tmp_path / "seed.json.imported").exists()


def test_clear_memories_foreign_key_safety():
    set_alias("ticket-tracker", "ticketera")
    m1 = upsert_memory("ticketera", "fact", "Old port was 8080", subject="port")
    # Supersede m1
    m2 = upsert_memory("ticket-tracker", "fact", "New port is 8081", subject="port", replaces_id=m1["id"])

    with get_connection() as conn:
        row = conn.execute("SELECT superseded_by FROM memories WHERE id = ?", (m1["id"],)).fetchone()
        assert row["superseded_by"] == m2["id"]

    # Scoped deletion of ticketera should safely null out foreign key references and delete without IntegrityError
    deleted = clear_memories(scope_filter="ticketera")
    assert deleted == 2
