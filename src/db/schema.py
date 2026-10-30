"""
SQLite Schema Initialization & DDL Management.

Creates memories, memories_fts, scope_aliases, and runtime_settings tables,
indexes, and full-text synchronization triggers.
"""

from src.db.connection import get_connection


def init_db() -> None:
    """
    Idempotent schema initialization.
    Creates tables, indexes, and triggers.
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
                stale_since TEXT DEFAULT NULL,
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
        try:
            conn.execute("ALTER TABLE memories ADD COLUMN stale_since TEXT DEFAULT NULL;")
        except Exception:
            pass
