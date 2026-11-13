"""Unit tests for onboarding bundles generation and get_client_setup_bundle tool."""

import re
import tomllib
from pathlib import Path

from src import __version__
from src.server import get_client_setup_bundle, recall_memories, save_memory


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
    assert f'directive_version="{__version__}"' in bundle_all
    assert f"(v{__version__})" in bundle_all
    assert "name: remember" in bundle_all
    assert "manage_git_webhooks" in bundle_all

    # 2. Server-CLI role
    bundle_server = get_client_setup_bundle(
        client="antigravity",
        os_platform="linux",
        instance_role="server-cli",
    )
    assert "~/.gemini/config/mcp_config.json" in bundle_server
    assert f'directive_version="{__version__}"' in bundle_server
    assert f"(Server CLI v{__version__})" in bundle_server
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


def test_directive_version_synced_with_package_and_container():
    repo_root = Path(__file__).resolve().parent.parent.parent
    pyproject_data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = pyproject_data["project"]["version"]
    assert __version__ == package_version

    # Docker build must retain pyproject.toml so container runtime does not fall back to 1.0.0
    dockerignore_lines = [
        line.strip()
        for line in (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "pyproject.toml" not in dockerignore_lines
    dockerfile_text = (repo_root / "Dockerfile").read_text(encoding="utf-8")
    assert "pyproject.toml" in dockerfile_text

    # Generated GEMINI.md directive block must match server __version__ and pass recall_memories without drift
    bundle = get_client_setup_bundle(client="antigravity", instance_role="workstation")
    match = re.search(r'directive_version="([^"]+)"', bundle)
    assert match is not None
    assert match.group(1) == package_version

    save_memory(scope="sync-check", category="fact", content="Version sync smoke test", subject="ver-sync")
    recalled = recall_memories(scope="sync-check", directive_version=match.group(1))
    assert "CLIENT DIRECTIVE DRIFT" not in recalled
