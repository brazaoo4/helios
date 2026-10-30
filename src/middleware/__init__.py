"""ASGI middleware, transport handlers, and application lifespan."""

from src.middleware.auth import (
    MAX_WEBHOOK_BYTES,
    AuthGateMiddleware,
    _read_bounded_body,
    is_request_authenticated,
)
from src.middleware.lifespan import lifespan
from src.middleware.transport import (
    HybridMCPHandler,
    StreamableMCPHandler,
    hybrid_handler,
    streamable_handler,
)

__all__ = [
    "AuthGateMiddleware",
    "HybridMCPHandler",
    "MAX_WEBHOOK_BYTES",
    "StreamableMCPHandler",
    "_read_bounded_body",
    "hybrid_handler",
    "is_request_authenticated",
    "lifespan",
    "streamable_handler",
]
