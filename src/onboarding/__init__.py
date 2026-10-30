"""Helios AI-driven client onboarding package."""

from src.onboarding.bundles import (
    generate_client_bundle,
    generate_setup_markdown,
)
from src.onboarding.client_config import (
    SUPPORTED_CLIENTS,
    get_directive_path,
    get_mcp_config_path,
    get_mcp_config_snippet,
    normalize_os_platform,
    resolve_server_base_url,
)
from src.onboarding.scripts_setup import (
    generate_setup_bash,
    generate_setup_powershell,
)
from src.onboarding.scripts_uninstall import (
    generate_uninstall_bash,
    generate_uninstall_powershell,
)
from src.onboarding.templates import (
    generate_global_directive,
    generate_guard_hook_script,
    generate_remember_skill,
)

__all__ = [
    "SUPPORTED_CLIENTS",
    "generate_client_bundle",
    "generate_global_directive",
    "generate_guard_hook_script",
    "generate_remember_skill",
    "generate_setup_bash",
    "generate_setup_markdown",
    "generate_setup_powershell",
    "generate_uninstall_bash",
    "generate_uninstall_powershell",
    "get_directive_path",
    "get_mcp_config_path",
    "get_mcp_config_snippet",
    "normalize_os_platform",
    "resolve_server_base_url",
]
