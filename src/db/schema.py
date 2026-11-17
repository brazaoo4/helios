"""
SQLite Schema Initialization & DDL Migrations.

Creates memories, memories_fts (Porter-stemmed FTS5), scope_aliases, and
runtime_settings tables, performance indexes, and versioned schema migrations.
"""

from src.db.connection import get_connection

_FTS_CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    scope,
    subject,
    content,
    content='memories',
    content_rowid='id',
    tokenize='porter unicode61'
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
"""


def init_db() -> None:
    """
    Idempotent schema initialization and PRAGMA user_version migrations.
    Creates tables, indexes, and Porter-stemmed FTS5 virtual table + triggers.
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
                hit_count INTEGER NOT NULL DEFAULT 0,
                updated_by TEXT DEFAULT '',
                last_verified_commit TEXT DEFAULT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_memories_active
            ON memories(scope, status, valid_to);

            CREATE INDEX IF NOT EXISTS idx_memories_slot
            ON memories(scope, subject, status);

            CREATE INDEX IF NOT EXISTS idx_memories_superseded_by
            ON memories(superseded_by);

            CREATE INDEX IF NOT EXISTS idx_memories_history
            ON memories(scope, status, valid_to DESC);

            CREATE TABLE IF NOT EXISTS scope_aliases (
                alias TEXT PRIMARY KEY,
                canonical_scope TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
                model TEXT NOT NULL,
                dims INTEGER NOT NULL,
                vec BLOB NOT NULL
            );
            """
        )

        existing_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(memories);").fetchall()
        }
        if "stale_since" not in existing_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN stale_since TEXT DEFAULT NULL;")
        if "updated_by" not in existing_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN updated_by TEXT DEFAULT '';")
        if "last_verified_commit" not in existing_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN last_verified_commit TEXT DEFAULT NULL;")

        user_version = conn.execute("PRAGMA user_version;").fetchone()[0]
        if user_version < 2:
            conn.executescript(
                f"""
                DROP TRIGGER IF EXISTS memories_ai;
                DROP TRIGGER IF EXISTS memories_ad;
                DROP TRIGGER IF EXISTS memories_au;
                DROP TABLE IF EXISTS memories_fts;
                {_FTS_CREATE_SQL}
                INSERT INTO memories_fts(memories_fts) VALUES('rebuild');
                """
            )
        else:
            conn.executescript(_FTS_CREATE_SQL)

        if user_version < 3:
            conn.execute("PRAGMA user_version = 3;")
