"""Health check telemetry endpoint with zero-trust unauthenticated redaction."""

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.db import get_connection
from src.middleware.auth import is_request_authenticated


def _query_health_status() -> tuple[str, int]:
    with get_connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        active_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status = 'active' AND valid_to IS NULL;"
        ).fetchone()[0]
    return journal_mode, active_count


async def health_check(request: Request) -> JSONResponse:
    is_auth = is_request_authenticated(request)
    try:
        journal_mode, active_count = await anyio.to_thread.run_sync(
            _query_health_status
        )

        if not is_auth:
            return JSONResponse(
                {
                    "status": "healthy",
                    "service": "helios",
                },
                status_code=200,
            )

        return JSONResponse(
            {
                "status": "healthy",
                "service": "helios",
                "database": {
                    "connected": True,
                    "journal_mode": journal_mode,
                    "active_memories": active_count,
                },
            },
            status_code=200,
        )
    except Exception as exc:
        if not is_auth:
            return JSONResponse(
                {
                    "status": "unhealthy",
                    "service": "helios",
                },
                status_code=503,
            )
        return JSONResponse(
            {
                "status": "unhealthy",
                "service": "helios",
                "error": str(exc),
            },
            status_code=503,
        )


__all__ = [
    "_query_health_status",
    "health_check",
]
