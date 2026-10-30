"""Unit tests for onboarding bundles generation and get_client_setup_bundle tool."""

from src.server import get_client_setup_bundle


def test_get_client_setup_bundle_tool():
    # 1. Default (all, auto, workstation)
    bundle_all = get_client_setup_bundle()
    assert "Antigravity" in bundle_all
    assert "Cursor" in bundle_all
    assert "Claude-desktop" in bundle_all
    assert "Claude-code" in bundle_all
    assert "Codex" in bundle_all
    assert "Windsurf" in bundle_all
    assert "Vscode" in bundle_all
    assert "Opencode" in bundle_all
    assert "GEMINI.md" in bundle_all
    assert "AGENTS.md" in bundle_all
    assert "copilot-instructions.md" in bundle_all
    assert "name: remember" in bundle_all
    assert "manage_git_webhooks" in bundle_all

    # 2. Server-CLI role
    bundle_server = get_client_setup_bundle(
        client="antigravity",
        os_platform="linux",
        instance_role="server-cli",
    )
    assert "~/.gemini/config/mcp_config.json" in bundle_server
    assert "docker logs --tail=50" in bundle_server
    assert "Cursor" not in bundle_server

    # 3. Action: install_or_update contains idempotent markers note
    bundle_update = get_client_setup_bundle(action="install_or_update")
    assert "Idempotent Update Rule" in bundle_update
    assert "<!-- HELIOS:START -->" in bundle_update
    assert "<!-- HELIOS:END -->" in bundle_update

    # 4. Action: uninstall provides clean removal instructions
    bundle_uninstall = get_client_setup_bundle(
        client="antigravity",
        os_platform="linux",
        action="uninstall",
    )
    assert "# Helios Client Uninstallation Guide" in bundle_uninstall
    assert "Remove MCP Server Entry" in bundle_uninstall
    assert "delete the section bounded by the Helios markers" in bundle_uninstall
    assert "Remove `/remember` Skill" in bundle_uninstall
    assert "Helios has been cleanly uninstalled" in bundle_uninstall

    # 5. Action: switch_role
    bundle_switch = get_client_setup_bundle(
        client="cursor",
        os_platform="linux",
        instance_role="server-cli",
        action="switch_role",
    )
    assert "Lifecycle Action**: `switch_role`" in bundle_switch
    assert "Instance Role**: `server-cli`" in bundle_switch
    assert "docker logs --tail=50" in bundle_switch
