"""FastMCP instance, transport security, and sync-tool thread offloading."""

import functools
from typing import Any

import anyio

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata
    from mcp.server.sse import TransportSecuritySettings
    from mcp.types import ToolAnnotations
except ImportError:
    try:
        from fastmcp import FastMCP
        from fastmcp.utilities.func_metadata import FuncMetadata
    except ImportError:
        FastMCP = None  # type: ignore[assignment, misc]
        FuncMetadata = None  # type: ignore[assignment, misc]
    TransportSecuritySettings = None  # type: ignore[assignment, misc]
    try:
        from mcp.types import ToolAnnotations
    except ImportError:
        from pydantic import BaseModel

        class ToolAnnotations(BaseModel):  # type: ignore[no-redef]
            readOnlyHint: bool = False
            destructiveHint: bool = False
            idempotentHint: bool = False
            openWorldHint: bool = False

# Offload sync FastMCP tools to worker thread via anyio.to_thread.run_sync during async MCP calls
if FuncMetadata is not None and not getattr(FuncMetadata, "_helios_offloaded", False):
    _orig_call_fn = FuncMetadata.call_fn_with_arg_validation

    async def _offloaded_call_fn(
        self: Any,
        fn: Any,
        fn_is_async: bool,
        arguments_to_validate: Any,
        arguments_to_pass_directly: Any,
    ) -> Any:
        arguments_pre_parsed = self.pre_parse_json(arguments_to_validate)
        arguments_parsed_model = self.arg_model.model_validate(arguments_pre_parsed)
        arguments_parsed_dict = arguments_parsed_model.model_dump_one_level()
        arguments_parsed_dict |= arguments_to_pass_directly or {}

        if fn_is_async:
            return await fn(**arguments_parsed_dict)
        else:
            return await anyio.to_thread.run_sync(functools.partial(fn, **arguments_parsed_dict))

    FuncMetadata.call_fn_with_arg_validation = _offloaded_call_fn
    FuncMetadata._helios_offloaded = True

HELIOS_INSTRUCTIONS = (
    "Helios is your centralized architectural memory across IDE and CLI agents. "
    "1. PRE-FLIGHT: Call recall_memories() at the start of any task using the current repo or folder name. "
    "2. STALE PROTOCOL: When a memory is marked [STALE], inspect the referenced anchor_files before acting. "
    "3. UPDATE RULE: If you modify an architecture choice, port, path, or bug fix, call save_memory() or deprecate_memory(). "
    "4. TOKEN BUDGET: Keep facts atomic (<= 25 words). Never store transient code snippets or secrets. "
    "5. UNINSTALL: If the user requests to uninstall Helios ('uninstall helios'), call get_client_setup_bundle(action='uninstall')."
)

transport_security = (
    TransportSecuritySettings(enable_dns_rebinding_protection=False)
    if TransportSecuritySettings is not None
    else None
)

mcp = FastMCP("Helios", instructions=HELIOS_INSTRUCTIONS, transport_security=transport_security)
if (
    hasattr(mcp, "settings")
    and hasattr(mcp.settings, "transport_security")
    and mcp.settings.transport_security
):
    mcp.settings.transport_security.enable_dns_rebinding_protection = False

_ = mcp.streamable_http_app()
sse_app = mcp.sse_app()

__all__ = [
    "HELIOS_INSTRUCTIONS",
    "FastMCP",
    "FuncMetadata",
    "ToolAnnotations",
    "TransportSecuritySettings",
    "mcp",
    "sse_app",
    "transport_security",
]
