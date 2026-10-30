"""HTTP endpoints for automated client setup and uninstallation runbooks."""

import anyio
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from src.config import get_api_key
from src.onboarding import (
    generate_client_bundle,
    generate_setup_bash,
    generate_setup_markdown,
    generate_setup_powershell,
    generate_uninstall_bash,
    generate_uninstall_powershell,
    resolve_server_base_url,
)


async def setup_instructions(request: Request) -> Response:
    """
    HTTP GET /setup endpoint returning self-contained setup instructions
    for AI agents (curl -fsSL https://<host>/setup).
    """
    headers_dict = dict(request.headers)
    base_url = resolve_server_base_url(headers_dict)
    has_auth = get_api_key() is not None
    query_token = request.query_params.get("token")
    content = await anyio.to_thread.run_sync(
        generate_setup_markdown,
        base_url,
        has_auth,
        query_token,
    )
    return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")


async def setup_powershell_script(request: Request) -> Response:
    """
    HTTP GET /setup.ps1 endpoint returning an automated 1-liner PowerShell setup script.
    Usage: irm https://<host>/setup.ps1 | iex
    Supports ?token=..., ?role=server-cli|workstation, ?client=all|cursor|antigravity
    """
    headers_dict = dict(request.headers)
    base_url = resolve_server_base_url(headers_dict)
    query_token = request.query_params.get("token")
    role = request.query_params.get("role", "workstation")
    client = request.query_params.get("client", "all")
    try:
        script = await anyio.to_thread.run_sync(
            generate_setup_powershell,
            base_url,
            query_token,
            role,
            client,
        )
        return PlainTextResponse(script, media_type="text/plain; charset=utf-8")
    except ValueError as exc:
        return PlainTextResponse(f"Error: {exc}\n", status_code=400)


async def setup_bash_script(request: Request) -> Response:
    """
    HTTP GET /setup.sh endpoint returning an automated 1-liner Bash setup script.
    Usage: curl -fsSL https://<host>/setup.sh | bash
    Supports ?token=..., ?role=server-cli|workstation, ?client=all|cursor|antigravity
    """
    headers_dict = dict(request.headers)
    base_url = resolve_server_base_url(headers_dict)
    query_token = request.query_params.get("token")
    role = request.query_params.get("role", "workstation")
    client = request.query_params.get("client", "all")
    try:
        script = await anyio.to_thread.run_sync(
            generate_setup_bash,
            base_url,
            query_token,
            role,
            client,
        )
        return PlainTextResponse(script, media_type="text/plain; charset=utf-8")
    except ValueError as exc:
        return PlainTextResponse(f"Error: {exc}\n", status_code=400)


async def uninstall_instructions(request: Request) -> Response:
    """
    HTTP GET /uninstall endpoint returning self-contained uninstallation instructions.
    Supports ?client=all|cursor|antigravity
    """
    headers_dict = dict(request.headers)
    base_url = resolve_server_base_url(headers_dict)
    client = request.query_params.get("client", "all")
    try:
        content = await anyio.to_thread.run_sync(
            generate_client_bundle,
            client,
            "auto",
            "workstation",
            base_url,
            "uninstall",
        )
        return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")
    except ValueError as exc:
        return PlainTextResponse(f"Error: {exc}\n", status_code=400)


async def uninstall_powershell_script(request: Request) -> Response:
    """
    HTTP GET /uninstall.ps1 endpoint returning an automated 1-liner PowerShell uninstaller.
    Usage: irm https://<host>/uninstall.ps1 | iex
    Supports ?client=all|cursor|antigravity
    """
    headers_dict = dict(request.headers)
    base_url = resolve_server_base_url(headers_dict)
    client = request.query_params.get("client", "all")
    try:
        script = await anyio.to_thread.run_sync(
            generate_uninstall_powershell,
            base_url,
            client,
        )
        return PlainTextResponse(script, media_type="text/plain; charset=utf-8")
    except ValueError as exc:
        return PlainTextResponse(f"Error: {exc}\n", status_code=400)


async def uninstall_bash_script(request: Request) -> Response:
    """
    HTTP GET /uninstall.sh endpoint returning an automated 1-liner Bash uninstaller.
    Usage: curl -fsSL https://<host>/uninstall.sh | bash
    Supports ?client=all|cursor|antigravity
    """
    headers_dict = dict(request.headers)
    base_url = resolve_server_base_url(headers_dict)
    client = request.query_params.get("client", "all")
    try:
        script = await anyio.to_thread.run_sync(
            generate_uninstall_bash,
            base_url,
            client,
        )
        return PlainTextResponse(script, media_type="text/plain; charset=utf-8")
    except ValueError as exc:
        return PlainTextResponse(f"Error: {exc}\n", status_code=400)


__all__ = [
    "setup_bash_script",
    "setup_instructions",
    "setup_powershell_script",
    "uninstall_bash_script",
    "uninstall_instructions",
    "uninstall_powershell_script",
]
