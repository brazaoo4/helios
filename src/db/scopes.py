"""
Scope Resolution & Alias Management.

Handles scope normalization, alias mapping, scope hierarchy flattening,
and cross-scope memory migration.
"""

import re
import sqlite3
from typing import Any

from src.db.connection import get_connection, get_db_path, now_iso


def _normalize_alias_key(raw_alias: str) -> str:
    """Normalize an alias or raw folder path into a clean lowercase lookup key."""
    if not raw_alias or not str(raw_alias).strip():
        return ""
    normalized = str(raw_alias).strip().replace("\\", "/").rstrip("/")
    folder_name = normalized.split("/")[-1].lower()
    while folder_name.endswith(".git"):
        folder_name = folder_name.removesuffix(".git")
    if folder_name in ("", ".", "..") or any(ord(c) < 32 for c in folder_name):
        return ""
    folder_name = re.sub(r"[^a-z0-9._-]", "-", folder_name).strip(".-")
    return folder_name


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
    if clean_scope == "global":
        raise ValueError("Cannot map a project alias directly to the reserved 'global' scope.")
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
        if clean_alias == clean_scope:
            conn.execute("DELETE FROM scope_aliases WHERE alias = ?", (clean_alias,))
            orig_target = _normalize_alias_key(canonical_scope)
            if orig_target and orig_target != clean_alias and orig_target != "global":
                clean_scope = orig_target
            else:
                raise ValueError("Alias and resolved canonical_scope cannot be identical.")

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


def migrate_scope(from_scope: str, to_scope: str, register_alias: bool = True) -> dict[str, Any]:
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

        # Resolve target to canonical scope if aliased
        target_row = conn.execute(
            "SELECT canonical_scope FROM scope_aliases WHERE alias = ?",
            (to_clean,),
        ).fetchone()
        if target_row:
            to_clean = target_row["canonical_scope"]
        if from_clean == to_clean:
            raise ValueError("Source and target scopes cannot be identical.")
        if to_clean == "global" and register_alias:
            raise ValueError("Cannot register an alias pointing to the reserved 'global' scope.")

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

        for _subj, rows in by_subject.items():
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
