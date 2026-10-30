"""
Day-2 Runtime Settings Storage.

Provides key-value persistence in the runtime_settings SQLite table.
"""

import sqlite3

from src.db.connection import get_connection, get_db_path, now_iso


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
