"""Starlette application lifespan context manager."""

import contextlib
import os
from collections.abc import AsyncGenerator

from starlette.applications import Starlette

from src.db import init_db
from src.exporter import sync_markdown_exports
from src.seed import ingest_declarative_seed_files, seed_if_empty
from src.tools import mcp


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
    init_db()
    ingest_declarative_seed_files()
    if os.getenv("HELIOS_AUTO_SEED", "false").lower() in ("1", "true", "yes"):
        seed_if_empty()
    sync_markdown_exports()
    if hasattr(mcp, "_session_manager") and mcp._session_manager is not None:
        if getattr(mcp._session_manager, "_has_started", False):
            mcp._session_manager = None
            _ = mcp.streamable_http_app()
    if hasattr(mcp, "session_manager") and mcp.session_manager:
        async with mcp.session_manager.run():
            yield
    else:
        yield


__all__ = ["lifespan"]
