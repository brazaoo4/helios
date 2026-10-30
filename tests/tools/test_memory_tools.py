"""Tests for FastMCP memory tools (recall, save, deprecate, revalidate, history)."""

import re

from starlette.testclient import TestClient

from src import __version__
from src.db import get_connection, set_alias
from src.exporter import get_export_dir
from src.server import (
    app,
    deprecate_memory,
    distill_memories,
    recall_history,
    recall_memories,
    revalidate_memories,
    save_memory,
)


def test_cold_start_onboarding_signal():
    # Database is completely empty on initial fixture setup
    recalled_cold = recall_memories(scope="webapp")
    assert "COLD START ONBOARDING" in recalled_cold
    assert "README.md" in recalled_cold
    assert "package.json" in recalled_cold

    # Once at least one active memory exists in the DB, empty scope query does NOT show cold start banner
    save_memory(scope="global", category="rule", content="Baseline global rule")
    recalled_non_empty = recall_memories(scope="other_scope", include_global=False)
    assert "COLD START ONBOARDING" not in recalled_non_empty
    assert "No active memories found for scope 'other_scope'." in recalled_non_empty


def test_recall_memories_directive_drift_detection():
    save_memory(scope="webapp", category="fact", content="Frontend runs on port 3000", subject="web-port")

    # 1. Legacy client (directive_version omitted / empty) -> shows drift banner
    recalled_legacy = recall_memories(scope="webapp")
    assert "CLIENT DIRECTIVE DRIFT" in recalled_legacy
    assert "unversioned/legacy" in recalled_legacy
    assert f"Helios Server v{__version__}" in recalled_legacy
    assert "Do NOT call save_memory for local client config updates" in recalled_legacy

    # 2. Outdated client (e.g. 1.2.0) -> shows drift banner with v1.2.0
    recalled_old = recall_memories(scope="webapp", directive_version="1.2.0")
    assert "CLIENT DIRECTIVE DRIFT" in recalled_old
    assert "v1.2.0" in recalled_old

    # 3. Matching client version -> NO drift banner
    recalled_current = recall_memories(scope="webapp", directive_version=__version__)
    assert "CLIENT DIRECTIVE DRIFT" not in recalled_current
    assert "Frontend runs on port 3000" in recalled_current

    # 4. Matching client version with 'v' prefix -> NO drift banner
    recalled_v_prefix = recall_memories(scope="webapp", directive_version=f"v{__version__}")
    assert "CLIENT DIRECTIVE DRIFT" not in recalled_v_prefix


def test_mcp_tools_lifecycle():
    set_alias("Infra-Repo", "infrastructure")

    # 1. Add (Create)
    res_save = save_memory(
        scope="Infra-Repo",
        category="fact",
        content="Metrics monitoring port is 8090",
        subject="metrics-port",
        anchor_files=["stacks/monitoring/compose.yaml"],
    )
    assert "created in scope 'infrastructure'" in res_save

    # 2. Recall
    recalled = recall_memories(scope="infrastructure", query="metrics")
    assert "8090" in recalled
    assert "[metrics-port]" in recalled

    # 3. No-op (Duplicate detection)
    res_noop = save_memory(
        scope="infrastructure",
        category="fact",
        content="Metrics monitoring port is 8090",
        subject="metrics-port",
    )
    assert "No-op" in res_noop

    # 4. Update / Slot Supersede
    res_update = save_memory(
        scope="infrastructure",
        category="fact",
        content="Metrics monitoring port changed to 8091",
        subject="metrics-port",
    )
    assert "superseding #1" in res_update

    # 5. Verify old fact is superseded and new fact is active
    recalled_updated = recall_memories(scope="infrastructure", query="metrics")
    assert "8091" in recalled_updated
    assert "8090" not in recalled_updated

    # 6. Deprecate
    res_deprecate = deprecate_memory(memory_id=2, reason="migrated to prometheus")
    assert "deprecated (archived)" in res_deprecate

    # 7. Recall should now find nothing active
    recalled_empty = recall_memories(scope="infrastructure", query="metrics")
    assert "No active memories found" in recalled_empty

    # 8. Recall history should list both superseded (#1) and archived (#2) entries
    history_out = recall_history(scope="infrastructure")
    assert "`#1` [superseded -> `#2`]" in history_out
    assert "`#2` [archived]" in history_out


def test_mcp_save_word_limit_guardrail():
    long_content = " ".join(["word"] * 26)
    res = save_memory(scope="infrastructure", category="fact", content=long_content)
    assert "Error saving memory" in res
    assert "exceeds 25-word limit" in res


def test_revalidate_memories_tool_and_markdown_sync():
    # Save memory with anchor_file
    save_res = save_memory(
        scope="service-a",
        category="fact",
        content="Service A binds to 0.0.0.0:4000",
        subject="host-port",
        anchor_files=["docker-compose.yml"],
    )
    # Extract memory ID from string e.g. "Memory #1 created..."
    m_id = int(re.search(r"#(\d+)", save_res).group(1))

    # Flag as stale via TestClient webhook
    with TestClient(app) as client:
        hook_payload = {
            "repository": {"name": "service-a"},
            "commits": [{"modified": ["docker-compose.yml"]}],
            "after": "deadbeef123",
        }
        res = client.post("/webhook/git", json=hook_payload)
        assert res.status_code == 200
        assert res.json()["memories_flagged_stale"] == 1

    # Verify memory is stale in recall and export
    recalled = recall_memories(scope="service-a", status_filter="stale")
    assert "[STALE:" in recalled

    export_file = get_export_dir() / "service-a.md"
    assert "[STALE:" in export_file.read_text(encoding="utf-8")

    # Revalidate using tool
    tool_res = revalidate_memories(memory_ids=[m_id])
    assert f"Revalidated 1 memories: #{m_id}" in tool_res

    # Check export was automatically synced and no longer has STALE
    assert "[STALE:" not in export_file.read_text(encoding="utf-8")
    recalled_active = recall_memories(scope="service-a", status_filter="active")
    assert "[STALE:" not in recalled_active
    assert "0.0.0.0:4000" in recalled_active


def test_recall_memories_category_and_status_filter_tools():
    save_memory(scope="shop", category="rule", content="Always use Decimal for currency", subject="money-rule")
    save_memory(scope="shop", category="fact", content="Checkout service on port 5005", subject="checkout-port")

    # Filter by category="rule"
    rule_res = recall_memories(scope="shop", category="rule")
    assert "Decimal for currency" in rule_res
    assert "Checkout service" not in rule_res

    # Filter by category="fact"
    fact_res = recall_memories(scope="shop", category="fact")
    assert "Checkout service" in fact_res
    assert "Decimal for currency" not in fact_res

    # Filter by status="stale" when none are stale
    stale_res = recall_memories(scope="shop", status_filter="stale")
    assert "No active memories found" in stale_res


def test_recall_memories_empty_category_normalization():
    save_memory(scope="shop", category="fact", content="Cart runs on port 4000", subject="cart-port")
    # Passing empty string category should not trigger Pydantic validation error and should return fact
    res = recall_memories(scope="shop", category="")
    assert "Cart runs on port 4000" in res


def test_recall_memories_stale_filter_does_not_bump_hit_count():
    save_memory(scope="audit-test", category="fact", content="Temporary facts on 8080", subject="tmp", anchor_files=["file.txt"])

    with TestClient(app) as client:
        client.post("/webhook/git", json={"repository": {"name": "audit-test"}, "commits": [{"modified": ["file.txt"]}]})

    with get_connection() as conn:
        row = conn.execute("SELECT hit_count FROM memories WHERE scope = 'audit-test'").fetchone()
        assert row["hit_count"] == 0

    # Recall with status_filter="stale" should NOT increment hit count
    stale_res = recall_memories(scope="audit-test", status_filter="stale")
    assert "Temporary facts on 8080" in stale_res

    with get_connection() as conn:
        row = conn.execute("SELECT hit_count FROM memories WHERE scope = 'audit-test'").fetchone()
        assert row["hit_count"] == 0

    # Normal recall should increment hit count
    act_res = recall_memories(scope="audit-test", status_filter="all")
    assert "Temporary facts on 8080" in act_res

    with get_connection() as conn:
        row = conn.execute("SELECT hit_count FROM memories WHERE scope = 'audit-test'").fetchone()
        assert row["hit_count"] == 1


def test_memory_tools_edge_cases_and_error_handling(monkeypatch):
    # 1. recall_history on empty scope
    hist_empty = recall_history(scope="empty_history_scope")
    assert "No historical memories on record for scope 'empty_history_scope'." in hist_empty

    # 2. revalidate_memories when none are stale or found
    reval_none = revalidate_memories(memory_ids=[99998, 99999])
    assert "No memories revalidated" in reval_none
    assert "#99998" in reval_none

    # 3. revalidate_memories with mixed valid stale and not-stale
    save_res = save_memory(scope="mixed-reval", category="fact", content="Fact for reval", anchor_files=["a.py"])
    mid = int(re.search(r"#(\d+)", save_res).group(1))
    # Mark stale
    with TestClient(app) as client:
        client.post("/webhook/git", json={"repository": {"name": "mixed-reval"}, "commits": [{"modified": ["a.py"]}]})

    reval_mixed = revalidate_memories(memory_ids=[mid, 88888])
    assert f"Revalidated 1 memories: #{mid}" in reval_mixed
    assert "Skipped 1 (not found or not stale): #88888" in reval_mixed

    # 4. deprecate_memory error handling for invalid/missing id
    dep_err = deprecate_memory(memory_id=-1)
    assert "Error deprecating memory" in dep_err

    # 5. save_memory word count error handling
    long_content = " ".join(["word"] * 40)
    save_err = save_memory(scope="test", category="fact", content=long_content)
    assert "Error saving memory" in save_err


def test_distill_memories_tool(monkeypatch):
    import unittest.mock as mock

    # 1. Invalid action
    res_invalid = distill_memories(scope="distill-test", action="invalid")  # type: ignore
    assert "Invalid action 'invalid'" in res_invalid

    # 2. Clean audit on empty scope
    res_audit_clean = distill_memories(scope="distill-clean", action="audit")
    assert "Memory bank is clean" in res_audit_clean
    assert "Active Memories**: 0" in res_audit_clean

    # 3. Clean suggest on empty scope
    res_suggest_clean = distill_memories(scope="distill-clean", action="suggest")
    assert "No slot collisions or near-duplicate facts detected" in res_suggest_clean

    # 4. Populate scope with:
    # - expired episodic memory
    # - stale memory (> 30d stale)
    # - potential slot collision pair
    # - cold memory (> 30d unaccessed, 0 hits)
    save_memory(
        scope="distill-test",
        category="episodic",
        content="Temporary sprint note about testing",
        subject="sprint-note",
    )
    save_memory(
        scope="distill-test",
        category="fact",
        content="Stale configuration for postgres host db.internal",
        subject="db-host",
    )
    # Collision pair:
    save_memory(
        scope="distill-test",
        category="fact",
        content="Postgres primary database server running on port 5432",
        subject="pg-port",
    )
    save_memory(
        scope="distill-test",
        category="fact",
        content="Postgres database listen port is 5432 for primary server",
        subject="pg-listen-port",
    )

    # Fast-forward timestamps in SQLite to simulate expiry, staleness, and age
    with get_connection() as conn:
        conn.execute(
            "UPDATE memories SET valid_from = datetime('now', '-15 days'), last_accessed = datetime('now', '-15 days') WHERE subject = 'sprint-note'"
        )
        conn.execute(
            "UPDATE memories SET status = 'stale', stale_reason = 'drift test', valid_from = datetime('now', '-35 days'), last_accessed = datetime('now', '-35 days') WHERE subject = 'db-host'"
        )
        conn.execute(
            "UPDATE memories SET valid_from = datetime('now', '-45 days'), last_accessed = datetime('now', '-35 days'), hit_count = 0 WHERE subject = 'pg-port'"
        )

    # 5. Audit populated scope
    res_audit = distill_memories(scope="distill-test", action="audit", stale_age_days=30)
    assert "Expired Episodic Notes (1)" in res_audit
    assert "Stale Backlog > 30d (1)" in res_audit
    assert "Cold Memories" in res_audit
    assert "Potential Slot Collisions" in res_audit
    assert "pg-port" in res_audit
    assert "pg-listen-port" in res_audit

    # 6. Suggest consolidations
    res_suggest = distill_memories(scope="distill-test", action="suggest")
    assert "Helios Consolidation Recommendations" in res_suggest
    assert "Recommendation 1: Consolidate" in res_suggest
    assert "save_memory" in res_suggest
    assert "deprecate_memory" in res_suggest

    # 7. Prune dry_run=True (Safety gate)
    res_dry_run = distill_memories(scope="distill-test", action="prune", dry_run=True, stale_age_days=30)
    assert "DRY RUN (no changes applied)" in res_dry_run
    assert "Expired episodic memories to archive: 1" in res_dry_run
    assert "Stale memories older than 30 days to archive: 1" in res_dry_run

    # Verify nothing was actually pruned yet
    with get_connection() as conn:
        active_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE scope = 'distill-test' AND status IN ('active', 'stale')"
        ).fetchone()[0]
        assert active_count == 4

    # 8. Prune dry_run=False (Apply pruning)
    res_prune = distill_memories(scope="distill-test", action="prune", dry_run=False, stale_age_days=30)
    assert "Archived 2 obsolete memories in scope 'distill-test'" in res_prune
    assert "Markdown exports synchronized" in res_prune

    # Prune again when nothing is left to prune
    res_prune_again = distill_memories(scope="distill-test", action="prune", dry_run=False, stale_age_days=30)
    assert "No memories met pruning criteria in scope 'distill-test'" in res_prune_again

    # 9. Error handling
    with mock.patch("src.tools.memory.db_audit_memories", side_effect=RuntimeError("Audit boom")):
        err_res = distill_memories(scope="distill-test", action="audit")
        assert "Error distilling memories: Audit boom" in err_res


