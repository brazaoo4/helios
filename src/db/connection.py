"""
SQLite Connection & Path Management.

Provides persistent WAL anchoring, thread-local connection reuse,
client attribution context, and data directory path resolution.
"""

import contextlib
import contextvars
import sqlite3
import threading
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_memory_data_dir

_CLIENT_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("helios_client_id", default="")

_POOL_LOCK = threading.RLock()
_WAL_ANCHORS: dict[Path, sqlite3.Connection] = {}
_ANCHOR_INODES: dict[Path, tuple[int, int] | None] = {}
_PATH_GENERATIONS: dict[Path, int] = {}
_NEXT_GEN = 0
_MAX_CACHED_PATHS = 4
_THREAD_LOCAL = threading.local()


class _ThreadConnectionBag:
    """Thread-local connection cache that closes cached connections when its thread exits."""

    def __init__(self) -> None:
        self.conns: dict[Path, tuple[int, sqlite3.Connection]] = {}
        self.in_use: set[Path] = set()

    def close_all(self) -> None:
        for _, conn in list(self.conns.values()):
            with contextlib.suppress(sqlite3.Error):
                conn.close()
        self.conns.clear()

    def __del__(self) -> None:
        self.close_all()


def get_client_id() -> str:
    """Return the active request's client attribution identifier (or '')."""
    return _CLIENT_ID_VAR.get()


def set_client_id(client_id: str) -> contextvars.Token[str]:
    """Bind a client attribution identifier to the current execution context."""
    return _CLIENT_ID_VAR.set((client_id or "").strip()[:64])


def reset_client_id(token: contextvars.Token[str]) -> None:
    """Restore the previous client attribution identifier from a ContextVar token."""
    _CLIENT_ID_VAR.reset(token)


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


def _configure_connection(conn: sqlite3.Connection) -> None:
    """Configure row factory and concurrency PRAGMAs once per connection."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=normal;")
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.execute("PRAGMA wal_autocheckpoint=1000;")
    conn.execute("PRAGMA foreign_keys=ON;")


def _db_inode(db_path: Path) -> tuple[int, int] | None:
    try:
        st = db_path.stat()
        return (st.st_dev, st.st_ino)
    except OSError:
        return None


def _ensure_wal_anchor(db_path: Path) -> int:
    """Ensure a persistent WAL anchor connection exists for db_path and return its generation."""
    global _NEXT_GEN
    with _POOL_LOCK:
        cur_inode = _db_inode(db_path)
        existing_anchor = _WAL_ANCHORS.get(db_path)
        if existing_anchor is not None:
            if cur_inode is None or cur_inode != _ANCHOR_INODES.get(db_path):
                with contextlib.suppress(sqlite3.Error):
                    existing_anchor.close()
                _WAL_ANCHORS.pop(db_path, None)
                _ANCHOR_INODES.pop(db_path, None)
                _PATH_GENERATIONS.pop(db_path, None)
            else:
                return _PATH_GENERATIONS[db_path]

        while len(_WAL_ANCHORS) >= _MAX_CACHED_PATHS:
            old_path = next(iter(_WAL_ANCHORS))
            old_anchor = _WAL_ANCHORS.pop(old_path)
            _ANCHOR_INODES.pop(old_path, None)
            _PATH_GENERATIONS.pop(old_path, None)
            with contextlib.suppress(sqlite3.Error):
                old_anchor.close()

        anchor = sqlite3.connect(
            db_path,
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
        _configure_connection(anchor)
        _NEXT_GEN += 1
        _WAL_ANCHORS[db_path] = anchor
        _ANCHOR_INODES[db_path] = _db_inode(db_path)
        _PATH_GENERATIONS[db_path] = _NEXT_GEN
        return _NEXT_GEN


def close_all_connections() -> None:
    """Close all cached WAL anchor connections and current-thread connections."""
    with _POOL_LOCK:
        for anchor in list(_WAL_ANCHORS.values()):
            with contextlib.suppress(sqlite3.Error):
                anchor.close()
        _WAL_ANCHORS.clear()
        _ANCHOR_INODES.clear()
        _PATH_GENERATIONS.clear()

    bag: _ThreadConnectionBag | None = getattr(_THREAD_LOCAL, "bag", None)
    if bag is not None:
        bag.close_all()


@contextlib.contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Thread-safe context manager for SQLite connections.

    1. Ensures target directory and persistent WAL anchor exist.
    2. Reuses a thread-local connection (isolation_level=None) configured once with WAL PRAGMAs.
    3. Commits active explicit transactions on clean exit, rolls back on exceptions.
    4. Falls back to an isolated temporary connection on reentrant calls within the same thread.
    """
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    gen = _ensure_wal_anchor(db_path)

    bag: _ThreadConnectionBag | None = getattr(_THREAD_LOCAL, "bag", None)
    if bag is None:
        bag = _ThreadConnectionBag()
        _THREAD_LOCAL.bag = bag

    conns = bag.conns
    in_use = bag.in_use

    is_reentrant = db_path in in_use
    cached_entry = None if is_reentrant else conns.get(db_path)

    if cached_entry is not None and cached_entry[0] == gen:
        conn = cached_entry[1]
    else:
        if cached_entry is not None:
            with contextlib.suppress(sqlite3.Error):
                cached_entry[1].close()
            conns.pop(db_path, None)
        while not is_reentrant and len(conns) >= _MAX_CACHED_PATHS:
            old_path = next(iter(conns))
            _, old_conn = conns.pop(old_path)
            with contextlib.suppress(sqlite3.Error):
                old_conn.close()
        conn = sqlite3.connect(
            db_path,
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
        _configure_connection(conn)
        if not is_reentrant:
            conns[db_path] = (gen, conn)

    if not is_reentrant:
        in_use.add(db_path)

    try:
        yield conn
        if conn.in_transaction:
            conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
        raise
    finally:
        if is_reentrant:
            with contextlib.suppress(sqlite3.Error):
                conn.close()
        else:
            in_use.discard(db_path)
