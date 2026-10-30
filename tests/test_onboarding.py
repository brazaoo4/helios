"""Integration and contract tests for the src.onboarding package re-exports and static invariants."""

from pathlib import Path

import src.onboarding as ob
from src.onboarding import (
    SUPPORTED_CLIENTS,
    generate_client_bundle,
    generate_global_directive,
    generate_guard_hook_script,
    generate_remember_skill,
    generate_setup_bash,
    generate_setup_markdown,
    generate_setup_powershell,
    generate_uninstall_bash,
    generate_uninstall_powershell,
    get_directive_path,
    get_mcp_config_path,
    get_mcp_config_snippet,
    normalize_os_platform,
    resolve_server_base_url,
)


def test_onboarding_package_reexports_contract():
    """Verify that src.onboarding exports all expected public APIs and types."""
    expected_symbols = [
        "SUPPORTED_CLIENTS",
        "resolve_server_base_url",
        "normalize_os_platform",
        "get_mcp_config_path",
        "get_directive_path",
        "get_mcp_config_snippet",
        "generate_global_directive",
        "generate_remember_skill",
        "generate_guard_hook_script",
        "generate_client_bundle",
        "generate_setup_markdown",
        "generate_setup_powershell",
        "generate_setup_bash",
        "generate_uninstall_powershell",
        "generate_uninstall_bash",
    ]

    for sym in expected_symbols:
        assert hasattr(ob, sym), f"src.onboarding is missing re-export for '{sym}'"
        assert sym in ob.__all__, f"'{sym}' not listed in src.onboarding.__all__"

    # Verify direct imports match module attributes
    assert ob.SUPPORTED_CLIENTS == SUPPORTED_CLIENTS
    assert ob.resolve_server_base_url == resolve_server_base_url
    assert ob.normalize_os_platform == normalize_os_platform
    assert ob.get_mcp_config_path == get_mcp_config_path
    assert ob.get_directive_path == get_directive_path
    assert ob.get_mcp_config_snippet == get_mcp_config_snippet
    assert ob.generate_global_directive == generate_global_directive
    assert ob.generate_remember_skill == generate_remember_skill
    assert ob.generate_guard_hook_script == generate_guard_hook_script
    assert ob.generate_client_bundle == generate_client_bundle
    assert ob.generate_setup_markdown == generate_setup_markdown
    assert ob.generate_setup_powershell == generate_setup_powershell
    assert ob.generate_setup_bash == generate_setup_bash
    assert ob.generate_uninstall_powershell == generate_uninstall_powershell
    assert ob.generate_uninstall_bash == generate_uninstall_bash


def test_no_os_environ_or_getenv_in_onboarding_package():
    """Verify zero os.environ or os.getenv inside src/onboarding package (Static Scanner Invariant)."""
    onboarding_files = list(Path("src/onboarding").glob("*.py"))
    assert len(onboarding_files) >= 5, "Expected modular onboarding package with multiple python modules"

    for py_file in onboarding_files:
        content = py_file.read_text(encoding="utf-8")
        assert "os.environ" not in content, f"{py_file} contains os.environ"
        assert "os.getenv" not in content, f"{py_file} contains os.getenv"
