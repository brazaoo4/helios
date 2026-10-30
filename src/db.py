import contextlib
import json
import re
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import (
    get_episodic_ttl_days,
    get_memory_data_dir,
    get_word_limit,
)


def get_data_dir() -> Path:
    """
    Resolve the data directory path dynamically via src.config.
    """
    return get_memory_data_dir()

def get_db_path() -> Path:
    """Return the absolute path to the active SQLite database file."""
    return get_data_dir() / "memory.db"

def now_iso() -> str:
    """Return current UTC timestamp in compact ISO-8601 format (e.g. 2026-10-20T17:38:00Z)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

@contextlib.contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Thread-safe context manager for SQLite connections.

    1. Ensures target directory exists.
    2. Opens SQLite connection with row dictionary mapping enabled.
    3. Sets high-concurrency PRAGMAs (WAL, busy timeout, foreign keys).
    4. Automatically commits on clean exit, rolls back on exceptions.
    5. Always closes the connection in a finally block to avoid file locks.
    """
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(get_db_path(), timeout=10.0)
    # Enable dict-like column access: row["content"] instead of row[4]
    conn.row_factory = sqlite3.Row

    # Performance and concurrency settings
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=normal;")
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.execute("PRAGMA wal_autocheckpoint=1000;")
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db() -> None:
    """
    Idempotent schema initialization.
    Creates tables, indexes, triggers and populates default scope aliases.
    """
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                category TEXT NOT NULL CHECK(category IN ('rule', 'fact', 'preference', 'episodic')),
                subject TEXT DEFAULT '',
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'stale', 'superseded', 'archived')),
                stale_reason TEXT DEFAULT '',
                anchor_files TEXT DEFAULT '[]',
                superseded_by INTEGER REFERENCES memories(id),
                valid_from TEXT NOT NULL,
                valid_to TEXT DEFAULT NULL,
                last_accessed TEXT NOT NULL,
                hit_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_memories_active
            ON memories(scope, status, valid_to);

            CREATE INDEX IF NOT EXISTS idx_memories_slot
            ON memories(scope, subject, status);

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                scope,
                subject,
                content,
                content='memories',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, scope, subject, content)
                VALUES (new.id, new.scope, new.subject, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, scope, subject, content)
                VALUES ('delete', old.id, old.scope, old.subject, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF scope, subject, content ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, scope, subject, content)
                VALUES ('delete', old.id, old.scope, old.subject, old.content);
                INSERT INTO memories_fts(rowid, scope, subject, content)
                VALUES (new.id, new.scope, new.subject, new.content);
            END;

            CREATE TABLE IF NOT EXISTS scope_aliases (
                alias TEXT PRIMARY KEY,
                canonical_scope TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def get_runtime_setting(key: str) -> str | None:
    """Fetch a runtime setting from the database, returning None if not found or table uninitialized."""
    if not key or not key.strip() or not get_db_path().exists():
        return None
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM runtime_settings WHERE key = ?",
                (key.strip(),),
            ).fetchone()
            return row["value"] if row else None
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return None


def set_runtime_setting(key: str, value: str) -> None:
    """Set or update a runtime setting in SQLite."""
    k = key.strip()
    if not k:
        raise ValueError("Setting key cannot be empty.")
    ts = now_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO runtime_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (k, str(value), ts),
        )


def delete_runtime_setting(key: str) -> bool:
    """Delete a runtime setting from SQLite. Returns True if deleted, False if not found."""
    k = key.strip()
    if not k:
        return False
    try:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("DELETE FROM runtime_settings WHERE key = ?", (k,))
            return cur.rowcount > 0
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return False


def list_runtime_settings() -> dict[str, str]:
    """Return all runtime settings currently stored in SQLite."""
    try:
        with get_connection() as conn:
            rows = conn.execute("SELECT key, value FROM runtime_settings ORDER BY key").fetchall()
            return {r["key"]: r["value"] for r in rows}
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return {}


def get_scope_statistics() -> list[dict[str, Any]]:
    """
    Return statistics for all memory scopes:
    [{"scope": ..., "active_count": int, "stale_count": int, "aliases": [...]}, ...]
    """
    with get_connection() as conn:
        aliases = list_aliases(conn=conn)
        aliases_by_canonical: dict[str, list[str]] = {}
        for alias, canonical in aliases.items():
            aliases_by_canonical.setdefault(canonical, []).append(alias)

        rows = conn.execute(
            """
            SELECT scope,
                   SUM(CASE WHEN status = 'active' AND valid_to IS NULL THEN 1 ELSE 0 END) as active_count,
                   SUM(CASE WHEN status = 'stale' AND valid_to IS NULL THEN 1 ELSE 0 END) as stale_count
            FROM memories
            GROUP BY scope
            ORDER BY active_count DESC, stale_count DESC, scope ASC
            """
        ).fetchall()

        stats = []
        for r in rows:
            sc = r["scope"]
            stats.append({
                "scope": sc,
                "active_count": r["active_count"] or 0,
                "stale_count": r["stale_count"] or 0,
                "aliases": sorted(aliases_by_canonical.get(sc, [])),
            })
        return stats


def _normalize_alias_key(raw_alias: str) -> str:
    """Normalize an alias or raw folder path into a clean lowercase lookup key."""
    if not raw_alias or not raw_alias.strip():
        return ""
    normalized = raw_alias.strip().replace("\\", "/").rstrip("/")
    folder_name = normalized.split("/")[-1].lower()
    folder_name = folder_name.removesuffix(".git")
    return folder_name


def _normalize_repo_path(path: str) -> str:
    """Normalize a repo-relative file path, stripping backslashes and redundant prefixes."""
    if not path or not path.strip():
        return ""
    p = path.strip().replace("\\", "/").strip("/")
    while p.startswith("./"):
        p = p[2:].strip("/")
    return p


def set_alias(alias: str, canonical_scope: str) -> None:
    """
    Create or update an alias mapping to a canonical memory scope.
    """
    clean_alias = _normalize_alias_key(alias)
    clean_scope = _normalize_alias_key(canonical_scope)
    if not clean_alias:
        raise ValueError("Alias cannot be empty.")
    if not clean_scope:
        raise ValueError("Canonical scope cannot be empty.")
    if clean_alias == "global":
        raise ValueError("Cannot alias or migrate the reserved 'global' scope.")
    if clean_alias == clean_scope:
        raise ValueError("Alias and canonical_scope cannot be identical.")

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        # Flatten: if clean_scope is already an alias, resolve to its canonical target
        target_row = conn.execute(
            "SELECT canonical_scope FROM scope_aliases WHERE alias = ?",
            (clean_scope,),
        ).fetchone()
        if target_row:
            clean_scope = target_row["canonical_scope"]

        conn.execute(
            """
            INSERT INTO scope_aliases (alias, canonical_scope)
            VALUES (?, ?)
            ON CONFLICT(alias) DO UPDATE SET canonical_scope = excluded.canonical_scope
            """,
            (clean_alias, clean_scope),
        )

        # Repoint any existing aliases targeting clean_alias to clean_scope
        conn.execute(
            "UPDATE scope_aliases SET canonical_scope = ? WHERE canonical_scope = ? AND alias != ?",
            (clean_scope, clean_alias, clean_scope),
        )


def remove_alias(alias: str) -> bool:
    """
    Remove an alias mapping from scope_aliases.
    Returns True if an alias was deleted, False if it did not exist.
    """
    clean_alias = _normalize_alias_key(alias)
    if not clean_alias:
        return False

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "DELETE FROM scope_aliases WHERE alias = ?",
            (clean_alias,),
        )
        return cur.rowcount > 0


def list_aliases(conn: sqlite3.Connection | None = None) -> dict[str, str]:
    """
    Return all current alias-to-canonical_scope mappings ordered by alias.
    """
    if conn is not None:
        rows = conn.execute(
            "SELECT alias, canonical_scope FROM scope_aliases ORDER BY alias"
        ).fetchall()
        return {r["alias"]: r["canonical_scope"] for r in rows}

    if not get_db_path().exists():
        return {}

    try:
        with get_connection() as c:
            rows = c.execute(
                "SELECT alias, canonical_scope FROM scope_aliases ORDER BY alias"
            ).fetchall()
            return {r["alias"]: r["canonical_scope"] for r in rows}
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return {}


def resolve_scope(raw_scope: str, conn: sqlite3.Connection | None = None) -> str:
    """
    Normalize raw directory paths, git repos, or aliases into a clean scope name.
    Queries scope_aliases dynamically, falling back to normalized directory/repo names.
    """
    if not raw_scope or not raw_scope.strip():
        return "global"

    folder_name = _normalize_alias_key(raw_scope)
    if not folder_name:
        return "global"

    if conn is not None:
        try:
            row = conn.execute(
                "SELECT canonical_scope FROM scope_aliases WHERE alias = ?",
                (folder_name,),
            ).fetchone()
            return row["canonical_scope"] if row else folder_name
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            return folder_name

    if not get_db_path().exists():
        return folder_name

    # Check if we have an alias in SQLite
    try:
        with get_connection() as c:
            row = c.execute(
                "SELECT canonical_scope FROM scope_aliases WHERE alias = ?",
                (folder_name,),
            ).fetchone()

            # If found in table, return canonical name; otherwise keep the folder name
            return row["canonical_scope"] if row else folder_name
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return folder_name


def migrate_scope(from_scope: str, to_scope: str, register_alias: bool = True) -> dict:
    """
    Migrate all memories from from_scope to to_scope.

    - Validates and normalizes scope names.
    - Resolves active slot collisions by superseding older records (by valid_from / id).
    - Updates all rows in memories where scope = from_clean to to_clean.
    - If register_alias=True, registers (from_clean, to_clean) in scope_aliases
      and repoints existing aliases targeting from_clean to to_clean.
    - Returns {"from_scope": from_clean, "to_scope": to_clean, "migrated_count": rowcount, "alias_registered": register_alias}.
    """
    from_clean = _normalize_alias_key(from_scope)
    to_clean = _normalize_alias_key(to_scope)
    if not from_clean:
        raise ValueError("Source scope cannot be empty.")
    if not to_clean:
        raise ValueError("Target scope cannot be empty.")
    if from_clean == "global":
        raise ValueError("Cannot alias or migrate the reserved 'global' scope.")
    if from_clean == to_clean:
        raise ValueError("Source and target scopes cannot be identical.")

    ts = now_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        # 1. Resolve active slot collisions for non-empty subjects
        colliding_rows = conn.execute(
            """
            SELECT id, scope, subject, valid_from
            FROM memories
            WHERE scope IN (?, ?) AND status IN ('active', 'stale') AND valid_to IS NULL AND subject != ''
            ORDER BY valid_from ASC, id ASC
            """,
            (from_clean, to_clean),
        ).fetchall()

        by_subject: dict[str, list[sqlite3.Row]] = {}
        for r in colliding_rows:
            by_subject.setdefault(r["subject"], []).append(r)

        for subj, rows in by_subject.items():
            scopes_present = {r["scope"] for r in rows}
            if from_clean in scopes_present and to_clean in scopes_present:
                # rows are sorted by valid_from ASC, id ASC; last one is newest (winner)
                winner = rows[-1]
                for older in rows[:-1]:
                    conn.execute(
                        "UPDATE memories SET status = 'superseded', valid_to = ?, superseded_by = ? WHERE id = ?",
                        (ts, winner["id"], older["id"]),
                    )

        # 2. Update all memories from from_clean to to_clean
        cur = conn.execute(
            "UPDATE memories SET scope = ? WHERE scope = ?",
            (to_clean, from_clean),
        )
        migrated_count = cur.rowcount

        # 3. Register and repoint aliases if requested
        if register_alias:
            conn.execute(
                """
                INSERT INTO scope_aliases (alias, canonical_scope)
                VALUES (?, ?)
                ON CONFLICT(alias) DO UPDATE SET canonical_scope = excluded.canonical_scope
                """,
                (from_clean, to_clean),
            )
            conn.execute(
                "UPDATE scope_aliases SET canonical_scope = ? WHERE canonical_scope = ? AND alias != ?",
                (to_clean, from_clean, to_clean),
            )
            conn.execute(
                "DELETE FROM scope_aliases WHERE alias = ?",
                (to_clean,),
            )

        return {
            "from_scope": from_clean,
            "to_scope": to_clean,
            "migrated_count": migrated_count,
            "alias_registered": register_alias,
        }


def prune_expired_episodic() -> int:
    """
    Archive temporary 'episodic' memories unaccessed for more than HELIOS_EPISODIC_TTL_DAYS days.

    Sets status='archived' and valid_to=now_iso().
    Leaves rules, facts, preferences, and recent episodic memories untouched.
    Returns the count of archived rows.
    """
    if not get_db_path().exists():
        return 0

    ttl_days = get_episodic_ttl_days()
    cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_connection() as conn:
        has_expired = conn.execute(
            "SELECT 1 FROM memories WHERE category = 'episodic' AND last_accessed < ? AND status IN ('active', 'stale') LIMIT 1",
            (cutoff,),
        ).fetchone()
        if not has_expired:
            return 0

        conn.execute("BEGIN IMMEDIATE")
        ts = now_iso()
        cur = conn.execute(
            """
            UPDATE memories
            SET status = 'archived', valid_to = ?
            WHERE category = 'episodic'
                AND last_accessed < ?
                AND status IN ('active', 'stale')
            """,
            (ts, cutoff),
        )
        return cur.rowcount


def db_audit_memories(
    raw_scope: str = "global",
    stale_age_days: int = 30,
) -> dict[str, Any]:
    """
    Audit memory hygiene for a specific scope or all scopes.
    Returns:
    - scope stats (active, stale, archived, word count)
    - expired episodic candidates
    - stale backlog older than stale_age_days
    - cold memories (0 hits, unaccessed > 30 days)
    - candidate slot collisions / near-duplicates within the scope
    """
    if not get_db_path().exists():
        return {
            "scope": raw_scope,
            "total_active": 0,
            "total_stale": 0,
            "total_archived": 0,
            "total_words": 0,
            "avg_words": 0.0,
            "expired_episodic": [],
            "stale_backlog": [],
            "cold_memories": [],
            "potential_collisions": [],
        }

    ttl_days = get_episodic_ttl_days()
    now_dt = datetime.now(UTC)
    episodic_cutoff = (now_dt - timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_cutoff = (now_dt - timedelta(days=stale_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cold_cutoff = (now_dt - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_connection() as conn:
        all_scopes_mode = raw_scope.strip().lower() in ("all", "*", "")
        if all_scopes_mode:
            target_scopes = None
        else:
            resolved = resolve_scope(raw_scope, conn=conn)
            target_scopes = [resolved]

        scope_clause = ""
        params: list[Any] = []
        if target_scopes:
            scope_clause = "AND scope = ?"
            params.append(target_scopes[0])

        # Active & stale memories
        active_rows = conn.execute(
            f"""
            SELECT id, scope, category, subject, content, status, stale_reason,
                   anchor_files, valid_from, last_accessed, hit_count
            FROM memories
            WHERE status IN ('active', 'stale') AND valid_to IS NULL {scope_clause}
            ORDER BY scope, id
            """,
            params,
        ).fetchall()

        # Archived count
        archived_count = conn.execute(
            f"SELECT COUNT(*) FROM memories WHERE status = 'archived' {scope_clause}",
            params,
        ).fetchone()[0]

        total_active = sum(1 for r in active_rows if r["status"] == "active")
        total_stale = sum(1 for r in active_rows if r["status"] == "stale")

        # Word counts
        word_counts = [len(r["content"].split()) for r in active_rows]
        total_words = sum(word_counts)
        avg_words = round(total_words / len(word_counts), 1) if word_counts else 0.0

        # Expired episodic
        expired_episodic = [
            {
                "id": r["id"],
                "scope": r["scope"],
                "subject": r["subject"],
                "content": r["content"],
                "last_accessed": r["last_accessed"],
            }
            for r in active_rows
            if r["category"] == "episodic" and r["last_accessed"] < episodic_cutoff
        ]

        # Stale backlog older than stale_age_days
        stale_backlog = [
            {
                "id": r["id"],
                "scope": r["scope"],
                "subject": r["subject"],
                "stale_reason": r["stale_reason"],
                "content": r["content"],
                "valid_from": r["valid_from"],
            }
            for r in active_rows
            if r["status"] == "stale" and r["valid_from"] < stale_cutoff
        ]

        # Cold memories (0 hits, active only, unaccessed > 30 days)
        cold_memories = [
            {
                "id": r["id"],
                "scope": r["scope"],
                "subject": r["subject"],
                "content": r["content"],
                "last_accessed": r["last_accessed"],
            }
            for r in active_rows
            if r["status"] == "active" and r["hit_count"] == 0 and r["last_accessed"] < cold_cutoff
        ]

        # Collision detection (group by scope first, then compare active memories within scope)
        potential_collisions: list[dict[str, Any]] = []
        by_scope: dict[str, list[dict[str, Any]]] = {}
        for r in active_rows:
            if r["status"] == "active":
                by_scope.setdefault(r["scope"], []).append(dict(r))

        stopwords = {
            "the", "is", "in", "to", "of", "for", "on", "with", "at", "by", "an", "be", "as", "and", "or", "a"
        }
        for s_name, mems in by_scope.items():
            if len(mems) < 2:
                continue
            mem_tokens: list[tuple[dict[str, Any], set[str]]] = []
            for m in mems:
                text = f"{m['subject']} {m['content']}".lower()
                toks = {
                    w.strip(".,;:?!-_()[]'\"")
                    for w in text.split()
                    if len(w.strip(".,;:?!-_()[]'\"")) > 2 and w.lower() not in stopwords
                }
                mem_tokens.append((m, toks))

            for i in range(len(mem_tokens)):
                for j in range(i + 1, len(mem_tokens)):
                    m1, t1 = mem_tokens[i]
                    m2, t2 = mem_tokens[j]
                    if not t1 or not t2:
                        continue
                    intersection = t1 & t2
                    union = t1 | t2
                    jaccard = len(intersection) / len(union) if union else 0.0
                    if jaccard >= 0.50 or (len(intersection) >= 3 and jaccard >= 0.35):
                        potential_collisions.append({
                            "scope": s_name,
                            "similarity": round(jaccard, 2),
                            "shared_terms": sorted(intersection),
                            "mem1": {"id": m1["id"], "subject": m1["subject"], "content": m1["content"]},
                            "mem2": {"id": m2["id"], "subject": m2["subject"], "content": m2["content"]},
                        })

        return {
            "scope": "all" if all_scopes_mode else target_scopes[0],
            "total_active": total_active,
            "total_stale": total_stale,
            "total_archived": archived_count,
            "total_words": total_words,
            "avg_words": avg_words,
            "expired_episodic": expired_episodic,
            "stale_backlog": stale_backlog,
            "cold_memories": cold_memories,
            "potential_collisions": potential_collisions,
        }


def db_prune_memories(
    raw_scope: str = "global",
    prune_stale: bool = True,
    stale_age_days: int = 30,
) -> dict[str, Any]:
    """
    Prune (archive) expired episodic memories and optionally old unreviewed stale memories.
    """
    if not get_db_path().exists():
        return {"scope": raw_scope, "pruned_episodic": 0, "pruned_stale": 0, "archived_ids": []}

    ttl_days = get_episodic_ttl_days()
    now_dt = datetime.now(UTC)
    episodic_cutoff = (now_dt - timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_cutoff = (now_dt - timedelta(days=stale_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts = now_iso()

    with get_connection() as conn:
        all_scopes_mode = raw_scope.strip().lower() in ("all", "*", "")
        if all_scopes_mode:
            target_scope = None
        else:
            target_scope = resolve_scope(raw_scope, conn=conn)

        scope_clause = "AND scope = ?" if target_scope else ""
        params_episodic: list[Any] = [episodic_cutoff]
        params_stale: list[Any] = [stale_cutoff]
        if target_scope:
            params_episodic.append(target_scope)
            params_stale.append(target_scope)

        conn.execute("BEGIN IMMEDIATE")

        # 1. Prune expired episodic
        cur_episodic = conn.execute(
            f"""
            UPDATE memories
            SET status = 'archived', valid_to = '{ts}'
            WHERE category = 'episodic'
              AND last_accessed < ?
              AND status IN ('active', 'stale')
              {scope_clause}
            RETURNING id
            """,
            params_episodic,
        )
        pruned_episodic_ids = [row[0] for row in cur_episodic.fetchall()]

        # 2. Prune old stale
        pruned_stale_ids: list[int] = []
        if prune_stale:
            cur_stale = conn.execute(
                f"""
                UPDATE memories
                SET status = 'archived', valid_to = '{ts}'
                WHERE status = 'stale'
                  AND valid_from < ?
                  AND valid_to IS NULL
                  {scope_clause}
                RETURNING id
                """,
                params_stale,
            )
            pruned_stale_ids = [row[0] for row in cur_stale.fetchall()]

        return {
            "scope": "all" if all_scopes_mode else target_scope,
            "pruned_episodic": len(pruned_episodic_ids),
            "pruned_stale": len(pruned_stale_ids),
            "archived_ids": sorted(pruned_episodic_ids + pruned_stale_ids),
        }


def upsert_memory(
    raw_scope: str,
    category: str,
    content: str,
    subject: str = "",
    anchor_files: list[str] | None = None,
    replaces_id: int | None = None,
) -> dict:
    """
    AUDN Write Gate:
    - Enforces category validation and a strict word limit (HELIOS_WORD_LIMIT).
    - Locks transaction with BEGIN IMMEDIATE to prevent write collisions.
    - Duplicate detection: returns 'no-op' and refreshes last_accessed.
    - Slot supersession: automatically retires older active records sharing (scope, subject).
    - Explicit supersession: validates and retires replaces_id if provided.
    """
    valid_categories = ("rule", "fact", "preference", "episodic")
    if category not in valid_categories:
        raise ValueError(f"Invalid category '{category}'. Must be one of: {valid_categories}")

    # Normalize whitespace (strip leading/trailing, collapse multiple spaces into one)
    content_clean = " ".join(content.strip().split())
    if not content_clean:
        raise ValueError("Memory content cannot be empty.")

    word_limit = get_word_limit()
    word_count = len(content_clean.split())
    if word_count > word_limit:
        raise ValueError(
            f"Content exceeds {word_limit}-word limit ({word_count} words; remove at least {word_count - word_limit} words). Keep facts atomic."
        )

    subject_clean = subject.strip().lower()
    normalized_anchors = list(
        dict.fromkeys(_normalize_repo_path(a) for a in (anchor_files or []) if _normalize_repo_path(a))
    )
    anchors_json = json.dumps(normalized_anchors)
    ts = now_iso()

    with get_connection() as conn:
        # BEGIN IMMEDIATE acquires a write lock up-front to prevent concurrent writer collisions
        conn.execute("BEGIN IMMEDIATE")
        scope = resolve_scope(raw_scope, conn=conn)

        # 1. Exact Duplicate Check (No-op or superseded if replaces_id passed)
        existing = conn.execute(
            """
            SELECT id FROM memories
            WHERE scope = ? AND category = ? AND subject = ? AND content = ? AND valid_to IS NULL
            """,
            (scope, category, subject_clean, content_clean),
        ).fetchone()

        if existing:
            superseded_ids = []
            if replaces_id is not None and replaces_id != existing["id"]:
                old_rec = conn.execute(
                    "SELECT id, scope FROM memories WHERE id = ? AND valid_to IS NULL",
                    (replaces_id,),
                ).fetchone()
                if not old_rec:
                    raise ValueError(f"replaces_id {replaces_id} does not exist or is already superseded.")
                if resolve_scope(old_rec["scope"], conn=conn) != scope:
                    raise ValueError(
                        f"Cannot supersede memory across different scopes ('{old_rec['scope']}' -> '{scope}')."
                    )
                conn.execute(
                    "UPDATE memories SET status = 'superseded', valid_to = ?, superseded_by = ? WHERE id = ?",
                    (ts, existing["id"], replaces_id),
                )
                superseded_ids.append(replaces_id)

            update_fields = ["status = 'active'", "stale_reason = ''", "last_accessed = ?"]
            params: list[Any] = [ts]
            if anchor_files is not None:
                update_fields.append("anchor_files = ?")
                params.append(anchors_json)
            params.append(existing["id"])
            conn.execute(
                f"UPDATE memories SET {', '.join(update_fields)} WHERE id = ?",
                tuple(params),
            )
            action = "superseded" if superseded_ids else "no-op (verified existing)"
            return {
                "action": action,
                "id": existing["id"],
                "scope": scope,
                "superseded_ids": superseded_ids,
            }

        # 2. Validate explicit replaces_id (if supplied)
        if replaces_id is not None:
            old_rec = conn.execute(
                "SELECT id, scope FROM memories WHERE id = ? AND valid_to IS NULL",
                (replaces_id,),
            ).fetchone()
            if not old_rec:
                raise ValueError(f"replaces_id {replaces_id} does not exist or is already superseded.")
            if resolve_scope(old_rec["scope"], conn=conn) != scope:
                raise ValueError(
                    f"Cannot supersede memory across different scopes ('{old_rec['scope']}' -> '{scope}')."
                )

        # 3. Insert New Memory Row
        cur = conn.execute(
            """
            INSERT INTO memories (
                scope, category, subject, content, status, anchor_files, valid_from, last_accessed
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (scope, category, subject_clean, content_clean, anchors_json, ts, ts),
        )
        new_id = cur.lastrowid
        superseded_ids = []

        # 4. Retire explicit replaces_id
        if replaces_id is not None:
            conn.execute(
                "UPDATE memories SET status = 'superseded', valid_to = ?, superseded_by = ? WHERE id = ?",
                (ts, new_id, replaces_id),
            )
            superseded_ids.append(replaces_id)

        # 5. Slot Supersession: Retire older active rows in the same (scope, subject) slot
        if subject_clean:
            old_slots = conn.execute(
                """
                SELECT id FROM memories
                WHERE scope = ? AND subject = ? AND id != ? AND valid_to IS NULL
                """,
                (scope, subject_clean, new_id),
            ).fetchall()
            for row in old_slots:
                if row["id"] not in superseded_ids:
                    conn.execute(
                        "UPDATE memories SET status = 'superseded', valid_to = ?, superseded_by = ? WHERE id = ?",
                        (ts, new_id, row["id"]),
                    )
                    superseded_ids.append(row["id"])

        return {
            "action": "superseded" if superseded_ids else "created",
            "id": new_id,
            "scope": scope,
            "superseded_ids": superseded_ids,
        }


SYNONYM_GROUPS: list[set[str]] = [
    # Database
    {"db", "database", "sql", "postgres", "postgresql", "mysql", "sqlite", "redis", "mongodb", "mongo"},
    # Networking & Ports
    {"port", "ports", "bind", "binding", "listen", "host", "hostname", "address", "ip", "subnet", "cidr"},
    # Auth & Security
    {"auth", "authentication", "login", "token", "jwt", "credentials", "key", "secret", "cert", "certificate", "tls", "ssl"},
    # Environment & Config
    {"env", "environment", "variable", "variables", "config", "configuration", "settings", "conf", "yaml", "toml"},
    # VCS & Repos
    {"repo", "repository", "git", "branch", "commit", "pr", "pull"},
    # Documentation & Rules
    {"doc", "docs", "documentation", "spec", "specification", "rule", "guardrail", "guideline", "policy"},
    # Deployment & Infrastructure
    {"deploy", "deployment", "docker", "compose", "stack", "container", "service", "k8s", "kubernetes", "homelab"},
    # Observability & Monitoring
    {"logs", "logging", "metrics", "monitor", "monitoring", "telemetry", "grafana", "prometheus"},
    # Errors & Debugging
    {"err", "error", "exception", "bug", "crash", "fail", "failure", "debug", "traceback"},
    # API & Transport
    {"api", "endpoint", "route", "http", "rest", "sse", "mcp", "webhook"},
]

_SYNONYM_LOOKUP: dict[str, tuple[str, ...]] = {}
for _group in SYNONYM_GROUPS:
    for _w in _group:
        _SYNONYM_LOOKUP[_w] = tuple(sorted(_group - {_w}))


def build_fts5_query(clean_tokens: list[str]) -> str:
    """
    Construct an FTS5 MATCH expression with synonym expansion.
    For each user token, if matching synonyms exist, creates an OR cluster:
    e.g. '("db"* OR "database"* OR "sql"*)'.
    """
    clusters: list[str] = []
    for tok in clean_tokens:
        tok_lower = tok.lower()
        synonyms = _SYNONYM_LOOKUP.get(tok_lower, ())
        top_syns = [s for s in synonyms if s != tok_lower][:3]
        if top_syns:
            syn_clauses = " OR ".join(f'"{s}"*' for s in top_syns)
            clusters.append(f'("{tok}"* OR {syn_clauses})')
        else:
            clusters.append(f'"{tok}"*')
    return " OR ".join(clusters)


def query_memories(
    raw_scope: str = "global",
    query: str = "",
    include_global: bool = True,
    limit: int = 8,
    category: str | None = None,
    status_filter: str = "all",
) -> list[dict]:
    """
    Retrieve active memories using FTS5 BM25 search or prioritized categorical fallback.

    - Prunes expired episodic memories first.
    - Searches both the resolved scope and 'global' (if include_global=True).
    - Clamps limit between 1 and 50.
    - Supports optional category filter ('rule', 'fact', 'preference', 'episodic').
    - Supports status_filter ('all' -> active & stale, 'active' -> active only, 'stale' -> stale only).
    - Increments hit_count and updates last_accessed for returned rows (except for administrative 'stale' audits).
    """
    prune_expired_episodic()

    limit = max(1, min(limit, 50))
    ts = now_iso()

    norm_status = (status_filter or "all").strip().lower()
    if norm_status == "active":
        status_clause_m = "m.status = 'active'"
        status_clause_bare = "status = 'active'"
    elif norm_status == "stale":
        status_clause_m = "m.status = 'stale'"
        status_clause_bare = "status = 'stale'"
    else:
        status_clause_m = "m.status IN ('active', 'stale')"
        status_clause_bare = "status IN ('active', 'stale')"

    cat_clean = category.strip().lower() if category and category.strip() else None
    cat_clause_m = "AND m.category = ?" if cat_clean else ""
    cat_clause_bare = "AND category = ?" if cat_clean else ""
    cat_params = [cat_clean] if cat_clean else []

    with get_connection() as conn:
        scope = resolve_scope(raw_scope, conn=conn)
        scopes = [scope]
        if include_global and scope != "global":
            scopes.append("global")
        placeholders = ",".join("?" for _ in scopes)

        if query.strip():
            # 1. Extract valid words/numbers/tokens, preserving technical punctuation (dots, colons, hyphens)
            clean_query = query.replace('"', ' ').replace('\x00', ' ')
            raw_tokens = re.findall(r"[\w.:-]+", clean_query, flags=re.UNICODE)
            clean_tokens = []
            for tok in raw_tokens:
                t = tok.strip("-_.:*")
                if not t:
                    continue
                if t.upper() in ("AND", "OR", "NOT"):
                    continue
                clean_tokens.append(t)

            # If multiple tokens exist, drop 1-char tokens and common stopwords
            if len(clean_tokens) > 1:
                stopwords = {"the", "is", "in", "to", "of", "for", "on", "with", "at", "by", "an", "be", "as"}
                filtered = [
                    t for t in clean_tokens
                    if len(t) > 1 and t.lower() not in stopwords
                ]
                if filtered:
                    clean_tokens = filtered

            # If user query was only punctuation/operators (e.g. '***:::'), return empty list safely
            if not clean_tokens:
                return []

            # 2. Quote each token as a prefix search cluster with synonym expansion
            fts_query = build_fts5_query(clean_tokens)

            try:
                rows = conn.execute(
                    f"""
                    SELECT m.id, m.scope, m.category, m.subject, m.content,
                           m.status, m.stale_reason, m.anchor_files
                    FROM memories_fts f
                    JOIN memories m ON f.rowid = m.id
                    WHERE m.scope IN ({placeholders})
                      AND {status_clause_m}
                      AND m.valid_to IS NULL
                      {cat_clause_m}
                      AND memories_fts MATCH ?
                    ORDER BY bm25(memories_fts, 5.0, 10.0, 1.0), m.hit_count DESC
                    LIMIT ?
                    """,
                    (*scopes, *cat_params, fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                # Failsafe fallback: return empty list on any syntax anomaly
                return []
        else:
            # Empty query: return rules first, then facts, preferences, episodic
            rows = conn.execute(
                f"""
                SELECT id, scope, category, subject, content, status, stale_reason, anchor_files
                FROM memories
                WHERE scope IN ({placeholders})
                  AND {status_clause_bare}
                  AND valid_to IS NULL
                  {cat_clause_bare}
                ORDER BY
                    CASE category
                        WHEN 'rule' THEN 1
                        WHEN 'fact' THEN 2
                        WHEN 'preference' THEN 3
                        ELSE 4
                    END,
                    hit_count DESC,
                    id DESC
                LIMIT ?
                """,
                (*scopes, *cat_params, limit),
            ).fetchall()

        results = [dict(r) for r in rows]

        # 3. Bump hit_count and refresh last_accessed for returned results (skip for administrative 'stale' audits)
        if results and norm_status != "stale":
            ids = [r["id"] for r in results]
            id_str = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE memories SET hit_count = hit_count + 1, last_accessed = ? WHERE id IN ({id_str})",
                (ts, *ids),
            )

        return results

def flag_stale_by_files(repo_name: str, modified_files: list[str], commit_sha: str) -> int:
    """
    Mark active memories as 'stale' if any of their anchor_files were modified in a Git commit.

    - Normalizes slashes and matches strictly on exact path or '/'-bounded path suffix.
    - Sets status='stale' and stale_reason='<matched_file> modified in commit <short_sha>'.
    - Returns the count of memories transitioned from active to stale.
    """
    if not modified_files:
        return 0

    short_sha = re.sub(r"[^a-zA-Z0-9._-]", "", commit_sha or "")[:7] or "latest"
    norm_modified = [_normalize_repo_path(f) for f in modified_files if _normalize_repo_path(f)]
    if not norm_modified:
        return 0

    flagged_count = 0
    with get_connection() as conn:
        scope = resolve_scope(repo_name, conn=conn)
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT id, anchor_files FROM memories
            WHERE scope IN (?, 'global') AND status = 'active' AND valid_to IS NULL
            """,
            (scope,),
        ).fetchall()

        for row in rows:
            try:
                raw_anchors = json.loads(row["anchor_files"] or "[]")
            except Exception:
                raw_anchors = []
            norm_anchors = [_normalize_repo_path(a) for a in raw_anchors if _normalize_repo_path(a)]

            matched_file = None
            for mod_file in norm_modified:
                for anchor in norm_anchors:
                    # Match only on exact path equality or clean '/' path boundary suffix
                    if mod_file == anchor or mod_file.endswith("/" + anchor):
                        matched_file = mod_file
                        break
                if matched_file:
                    break

            if matched_file:
                clean_matched = re.sub(r"[^a-zA-Z0-9_./-]", "", matched_file)[:120]
                reason = f"{clean_matched} modified in commit {short_sha}"
                conn.execute(
                    "UPDATE memories SET status = 'stale', stale_reason = ? WHERE id = ?",
                    (reason, row["id"]),
                )
                flagged_count += 1

    return flagged_count

def deprecate_memory(memory_id: int, reason: str = "") -> dict:
    """
    AUDN Deprecate Gate:
    Retires an active or stale memory into 'archived' status with valid_to stamped.
    """
    ts = now_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, scope, subject, content, status FROM memories WHERE id = ? AND valid_to IS NULL",
            (memory_id,),
        ).fetchone()

        if not row:
            raise ValueError(f"Memory #{memory_id} does not exist or is already inactive.")

        stale_reason = reason.strip() if reason.strip() else "deprecated by user/agent"
        conn.execute(
            "UPDATE memories SET status = 'archived', valid_to = ?, stale_reason = ? WHERE id = ?",
            (ts, stale_reason, memory_id),
        )

        return {
            "action": "deprecated",
            "id": memory_id,
            "scope": row["scope"],
            "subject": row["subject"],
            "content": row["content"],
        }


def revalidate_memories(memory_ids: list[int]) -> dict:
    """
    Batch revalidate stale memories back to 'active' status.
    For matching rows where status = 'stale' and valid_to IS NULL:
      - sets status = 'active', stale_reason = '', last_accessed = now_iso()
    Returns {"revalidated_ids": [...], "not_found_or_not_stale_ids": [...]}.
    """
    if not memory_ids:
        return {"revalidated_ids": [], "not_found_or_not_stale_ids": []}

    unique_ids = list(dict.fromkeys(memory_ids))
    ts = now_iso()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in unique_ids)
        rows = conn.execute(
            f"SELECT id, status, valid_to FROM memories WHERE id IN ({placeholders})",
            unique_ids,
        ).fetchall()

        stale_ids = {r["id"] for r in rows if r["status"] == "stale" and r["valid_to"] is None}

        if stale_ids:
            update_placeholders = ",".join("?" for _ in stale_ids)
            conn.execute(
                f"""
                UPDATE memories
                SET status = 'active', stale_reason = '', last_accessed = ?
                WHERE id IN ({update_placeholders})
                """,
                (ts, *stale_ids),
            )

        revalidated = [mid for mid in unique_ids if mid in stale_ids]
        not_found_or_not_stale = [mid for mid in unique_ids if mid not in stale_ids]

        return {
            "revalidated_ids": revalidated,
            "not_found_or_not_stale_ids": not_found_or_not_stale,
        }
