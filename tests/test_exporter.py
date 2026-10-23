import sqlite3
import tarfile
from pathlib import Path
import pytest

from src.db import flag_stale_by_files, get_connection, init_db, set_alias, upsert_memory
from src.exporter import (
    atomic_write,
    create_portable_archive,
    get_changelog_dir,
    get_export_dir,
    sanitize_filename,
    sync_markdown_exports,
)


@pytest.fixture(autouse=True)
def setup_test_exporter_env(tmp_path, monkeypatch):
    """
    Runs before every test:
    Isolates MEMORY_DATA_DIR to a temporary folder and initializes the DB.
    """
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path))
    init_db()


# --- 1. Helper Functions ---

def test_sanitize_filename():
    assert sanitize_filename("infrastructure") == "infrastructure"
    assert sanitize_filename("foo/bar..baz") == "foo_bar__baz"
    assert sanitize_filename("web-service_1") == "web-service_1"
    assert sanitize_filename("   ") == "unnamed_scope"


def test_atomic_write(tmp_path):
    target_file = tmp_path / "subfolder" / "atomic_target.txt"
    content = "Atomic file content\nLine 2\n"

    atomic_write(target_file, content)
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == content

    # Overwrite test
    updated_content = "Replaced atomically\n"
    atomic_write(target_file, updated_content)
    assert target_file.read_text(encoding="utf-8") == updated_content


# --- 2. Active & Stale Markdown Exports ---

def test_sync_markdown_exports_active_and_stale():
    set_alias("Infra-Repo", "infrastructure")
    # Insert facts across scopes
    upsert_memory("global", "rule", "Always filter logs with tail=50", subject="token-diet")
    upsert_memory(
        "Infra-Repo",
        "fact",
        "Metrics server runs on 8090",
        subject="metrics",
        anchor_files=["stacks/monitoring/compose.yaml"],
    )
    upsert_memory("Infra-Repo", "preference", "Prefer dark theme in dashboards")

    # Supersede a fact (must NOT show in active export)
    upsert_memory("Infra-Repo", "fact", "Old port was 7070", subject="dashboard-port")
    upsert_memory("Infra-Repo", "fact", "New port is 7071", subject="dashboard-port")

    # Mark metrics as stale
    flag_stale_by_files("infrastructure", ["stacks/monitoring/compose.yaml"], "sha12345")

    written = sync_markdown_exports()
    export_dir = get_export_dir()

    assert str(export_dir / "global.md") in written
    assert str(export_dir / "infrastructure.md") in written

    infra_content = (export_dir / "infrastructure.md").read_text(encoding="utf-8")

    assert "# Memory Scope: `infrastructure`" in infra_content
    assert "**[metrics]** Metrics server runs on 8090" in infra_content
    assert "[STALE: stacks/monitoring/compose.yaml modified in commit sha1234]" in infra_content
    assert "(anchors: `stacks/monitoring/compose.yaml`)" in infra_content
    assert "**[dashboard-port]** New port is 7071" in infra_content
    assert "Old port was 7070" not in infra_content  # Superseded fact excluded

    # If all active memories in a scope are archived, scope file must be unlinked
    with get_connection() as conn:
        conn.execute("UPDATE memories SET status = 'archived', valid_to = '2026-10-21T00:00:00Z' WHERE scope = 'global'")
    sync_markdown_exports()
    assert not (export_dir / "global.md").exists()

    # If a scope is completely deleted from the DB, orphaned .md and _history.md files must be cleaned up
    with get_connection() as conn:
        conn.execute("DELETE FROM memories WHERE scope = 'infrastructure'")
    sync_markdown_exports()
    assert not (export_dir / "infrastructure.md").exists()
    assert not (get_changelog_dir() / "infrastructure_history.md").exists()


# --- 3. Changelog Audit Trail ---

def test_sync_markdown_exports_changelog():
    # 1. Superseded fact with replacement
    res1 = upsert_memory("infrastructure", "fact", "Version 1.0 config", subject="app-cfg")
    res2 = upsert_memory("infrastructure", "fact", "Version 2.0 config", subject="app-cfg")

    # 2. Fact archived without replacement
    res3 = upsert_memory("infrastructure", "episodic", "Temporary triage note", subject="temp-note")
    with get_connection() as conn:
        conn.execute(
            "UPDATE memories SET status = 'archived', valid_to = '2026-10-21T00:00:00Z' WHERE id = ?",
            (res3["id"],),
        )

    sync_markdown_exports()

    changelog_dir = get_changelog_dir()
    infra_hist = changelog_dir / "infrastructure_history.md"
    global_hist = changelog_dir / "global_history.md"

    # Only infrastructure has historical records
    assert infra_hist.exists()
    assert not global_hist.exists()

    hist_content = infra_hist.read_text(encoding="utf-8")
    assert "# Changelog Audit: `infrastructure`" in hist_content
    assert f"`#{res1['id']}` [superseded -> replaced by `#{res2['id']}`]" in hist_content
    assert "**[app-cfg]** Version 1.0 config" in hist_content
    assert f"`#{res3['id']}` [archived]" in hist_content
    assert "**[temp-note]** Temporary triage note" in hist_content


# --- 4. Portable Archive Creation & SQLite Integrity ---

def test_create_portable_archive(tmp_path):
    upsert_memory("infrastructure", "fact", "Postgres runs on port 5432", subject="db-port")
    upsert_memory("global", "rule", "Enforce strict token diets")

    archive_path = create_portable_archive()
    archive_file = Path(archive_path)

    assert archive_file.exists()
    assert archive_file.name == "helios_portable_bundle.tar.gz"

    # Extract archive and verify contents
    extract_dir = tmp_path / "extracted_bundle"
    extract_dir.mkdir()

    with tarfile.open(archive_file, "r:gz") as tar:
        tar.extractall(extract_dir)

    extracted_db = extract_dir / "memory.db"
    extracted_exports = extract_dir / "exports"

    assert extracted_db.exists()
    assert extracted_exports.exists()
    assert (extracted_exports / "infrastructure.md").exists()
    assert (extracted_exports / "global.md").exists()

    # Check database integrity of the snapshot
    conn = sqlite3.connect(extracted_db)
    integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
    count = conn.execute("SELECT COUNT(*) FROM memories;").fetchone()[0]
    conn.close()

    assert integrity == "ok"
    assert count == 2
