"""Starlette application lifespan context manager."""

import contextlib
import logging
import os
from collections.abc import AsyncGenerator

from starlette.applications import Starlette

from src.config import get_semantic_search_enabled
from src.db import close_all_connections, get_connection, get_db_path, init_db
from src.exporter import sync_markdown_exports
from src.logging_config import configure_logging
from src.seed import ingest_declarative_seed_files, seed_if_empty
from src.tools import mcp

logger = logging.getLogger("helios.lifespan")


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
    configure_logging()
    init_db()
    ingested = ingest_declarative_seed_files()
    if os.getenv("HELIOS_AUTO_SEED", "false").lower() in ("1", "true", "yes"):
        seed_if_empty()
    sync_markdown_exports()

    with get_connection() as conn:
        user_ver = conn.execute("PRAGMA user_version;").fetchone()[0]
        active_cnt = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status IN ('active', 'stale') AND valid_to IS NULL"
        ).fetchone()[0]
    logger.info(
        "Helios ready: db=%s schema=v%d active_memories=%d seed_ingested=%d semantic_search=%s",
        get_db_path(),
        user_ver,
        active_cnt,
        ingested,
        "enabled" if get_semantic_search_enabled() else "disabled",
    )

    if hasattr(mcp, "_session_manager") and mcp._session_manager is not None:
        if getattr(mcp._session_manager, "_has_started", False):
            mcp._session_manager = None
            _ = mcp.streamable_http_app()
    try:
        if hasattr(mcp, "session_manager") and mcp.session_manager:
            async with mcp.session_manager.run():
                yield
        else:
            yield
    finally:
        close_all_connections()
        logger.info("Helios shutdown complete")


__all__ = ["lifespan"]
