"""
Helios SQLite Database Engine Package.

Provides connection management, schema initialization, Day-2 runtime settings,
scope resolution and migration, memory AUDN lifecycle operations, FTS5 synonym-expanded
BM25 search, Git anchor drift tracking, and distillation/hygiene auditing.
"""

from src.db.audit import db_audit_memories, db_prune_memories
from src.db.connection import (
    get_connection,
    get_data_dir,
    get_db_path,
    now_iso,
)
from src.db.drift import _normalize_repo_path, flag_stale_by_files
from src.db.memories import (
    deprecate_memory,
    prune_expired_episodic,
    revalidate_memories,
    upsert_memory,
)
from src.db.schema import init_db
from src.db.scopes import (
    _normalize_alias_key,
    get_scope_statistics,
    list_aliases,
    migrate_scope,
    remove_alias,
    resolve_scope,
    set_alias,
)
from src.db.search import (
    SYNONYM_GROUPS,
    build_fts5_query,
    query_memories,
)
from src.db.settings import (
    delete_runtime_setting,
    get_runtime_setting,
    list_runtime_settings,
    set_runtime_setting,
)

__all__ = [
    "SYNONYM_GROUPS",
    "_normalize_alias_key",
    "_normalize_repo_path",
    "build_fts5_query",
    "db_audit_memories",
    "db_prune_memories",
    "delete_runtime_setting",
    "deprecate_memory",
    "flag_stale_by_files",
    "get_connection",
    "get_data_dir",
    "get_db_path",
    "get_runtime_setting",
    "get_scope_statistics",
    "init_db",
    "list_aliases",
    "list_runtime_settings",
    "migrate_scope",
    "now_iso",
    "prune_expired_episodic",
    "query_memories",
    "remove_alias",
    "resolve_scope",
    "revalidate_memories",
    "set_alias",
    "set_runtime_setting",
    "upsert_memory",
]
