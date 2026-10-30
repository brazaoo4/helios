"""Starlette HTTP route registry and endpoint definitions."""

from starlette.routing import Mount, Route

from src.middleware.transport import hybrid_handler, streamable_handler
from src.routes.exports import (
    _scan_markdown_exports,
    export_bundle_download,
    list_markdown_exports,
)
from src.routes.git_webhooks import (
    _detect_webhook_provider_and_verify,
    _is_push_event,
    _process_webhook_drift,
    forgejo_webhook,
    git_webhook,
    verify_forgejo_signature,
    verify_github_signature,
)
from src.routes.health import _query_health_status, health_check
from src.routes.setup import (
    setup_bash_script,
    setup_instructions,
    setup_powershell_script,
    uninstall_bash_script,
    uninstall_instructions,
    uninstall_powershell_script,
)
from src.tools import sse_app

starlette_routes = [
    Route("/health", health_check, methods=["GET"]),
    Route("/setup", setup_instructions, methods=["GET"]),
    Route("/setup.ps1", setup_powershell_script, methods=["GET"]),
    Route("/setup.sh", setup_bash_script, methods=["GET"]),
    Route("/uninstall", uninstall_instructions, methods=["GET"]),
    Route("/uninstall.ps1", uninstall_powershell_script, methods=["GET"]),
    Route("/uninstall.sh", uninstall_bash_script, methods=["GET"]),
    Route("/export/bundle", export_bundle_download, methods=["GET"]),
    Route("/export/markdown", list_markdown_exports, methods=["GET"]),
    Route("/webhook/git", git_webhook, methods=["POST"]),
    Route("/webhook/forgejo", forgejo_webhook, methods=["POST"]),
    Route("/hooks/git-commit", git_webhook, methods=["POST"]),
    Route("/sse", endpoint=hybrid_handler),
    Route("/mcp", endpoint=streamable_handler or hybrid_handler),
    Mount("/", app=sse_app),
]

__all__ = [
    "_detect_webhook_provider_and_verify",
    "_is_push_event",
    "_process_webhook_drift",
    "_query_health_status",
    "_scan_markdown_exports",
    "export_bundle_download",
    "forgejo_webhook",
    "git_webhook",
    "health_check",
    "list_markdown_exports",
    "setup_bash_script",
    "setup_instructions",
    "setup_powershell_script",
    "starlette_routes",
    "uninstall_bash_script",
    "uninstall_instructions",
    "uninstall_powershell_script",
    "verify_forgejo_signature",
    "verify_github_signature",
]
