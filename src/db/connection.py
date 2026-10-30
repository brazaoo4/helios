"""
SQLite Connection & Path Management.

Provides thread-safe connection lifecycle, WAL pragma enforcement,
and data directory path resolution.
"""

import contextlib
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_memory_data_dir


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
