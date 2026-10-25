import json
import pytest
from starlette.testclient import TestClient

from src.onboarding import (
    generate_client_bundle,
    generate_global_directive,
    generate_remember_skill,
    generate_setup_markdown,
    get_mcp_config_path,
    get_mcp_config_snippet,
    normalize_os_platform,
    resolve_server_base_url,
)
from src.server import app, get_client_setup_bundle


@pytest.fixture(autouse=True)
def setup_onboarding_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HELIOS_PUBLIC_URL", raising=False)
    monkeypatch.delenv("HELIOS_API_KEY", raising=False)


def test_resolve_server_base_url(monkeypatch):
    # 1. Fallback default
    assert resolve_server_base_url() == "http://localhost:8000"

    # 2. Request headers
    headers = {
        "x-forwarded-proto": "https",
        "x-forwarded-host": "helios.example.com",
    }
    assert resolve_server_base_url(headers) == "https://helios.example.com"

    # 3. HELIOS_PUBLIC_URL takes precedence
    monkeypatch.setenv("HELIOS_PUBLIC_URL", "https://public-mesh.site:8443/")
    assert resolve_server_base_url(headers) == "https://public-mesh.site:8443"


def test_normalize_os_platform():
    assert normalize_os_platform("win") == "windows"
    assert normalize_os_platform("darwin") == "macos"
    assert normalize_os_platform("ubuntu") == "linux"


def test_mcp_config_paths_and_snippets():
    # Antigravity paths
    assert get_mcp_config_path("antigravity", "linux") == "~/.gemini/config/mcp_config.json"
    assert get_mcp_config_path("antigravity", "windows") == r"%USERPROFILE%\.gemini\config\mcp_config.json"

    # Cursor paths
    assert get_mcp_config_path("cursor", "linux") == "~/.cursor/mcp.json"
    assert get_mcp_config_path("cursor", "windows") == r"%USERPROFILE%\.cursor\mcp.json"

    # Claude Desktop paths
    assert get_mcp_config_path("claude-desktop", "macos") == "~/Library/Application Support/Claude/claude_desktop_config.json"
    assert get_mcp_config_path("claude-desktop", "windows") == r"%APPDATA%\Claude\claude_desktop_config.json"

    # Snippets
    anti_cfg = get_mcp_config_snippet("antigravity", "https://helios.example.com")
    assert isinstance(anti_cfg, dict)
    assert anti_cfg["mcpServers"]["helios"]["url"] == "https://helios.example.com/mcp"

    claude_cfg = get_mcp_config_snippet("claude-desktop", "https://helios.example.com", token="tok123")
    assert isinstance(claude_cfg, dict)
    assert claude_cfg["mcpServers"]["helios"]["args"] == ["-y", "mcp-remote", "https://helios.example.com/sse?token=tok123"]

    cli_cmd = get_mcp_config_snippet("claude-code", "https://helios.example.com")
    assert cli_cmd == "claude mcp add --transport sse helios https://helios.example.com/sse"


def test_global_directive_roles():
    workstation_directive = generate_global_directive("workstation")
    assert workstation_directive.startswith("<!-- HELIOS:START -->")
    assert workstation_directive.strip().endswith("<!-- HELIOS:END -->")
    assert "Pre-Flight Memory Check" in workstation_directive
    assert "<= 25 words" in workstation_directive
    assert "docker logs --tail=50" not in workstation_directive

    # Test dynamic word limit injection
    custom_word_directive = generate_global_directive("workstation", word_limit=45)
    assert "<= 45 words" in custom_word_directive

    server_directive = generate_global_directive("server-cli")
    assert server_directive.startswith("<!-- HELIOS:START -->")
    assert server_directive.strip().endswith("<!-- HELIOS:END -->")
    assert "Pre-Flight Memory Check" in server_directive
    assert "homelab" in server_directive
    assert "docker logs --tail=50" in server_directive
    assert "journalctl -n 40 --no-pager" in server_directive
    assert "git status -s" in server_directive


def test_remember_skill_content():
    skill = generate_remember_skill()
    assert "name: remember" in skill
    assert "save_memory" in skill
    assert "revalidate_memories" in skill
    assert "deprecate_memory" in skill


def test_http_setup_endpoint_open_mode():
    with TestClient(app) as client:
        res = client.get("/setup", headers={"Host": "helios.local:8000"})
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/markdown")
        content = res.text
        assert "Helios AI-Driven Client Onboarding" in content
        assert "http://helios.local:8000" in content
        assert "mcp_config.json" in content
        assert "name: remember" in content
        assert "manage_git_webhooks" in content


def test_http_setup_endpoint_with_auth_and_no_leak(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "super-secret-production-token-999")

    with TestClient(app) as client:
        # 1. Unauthenticated request to /setup must succeed (exempt from AuthGate)
        res = client.get(
            "/setup",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "helios.internal.net",
            },
        )
        assert res.status_code == 200
        content = res.text

        # Base URL must be correctly resolved from headers
        assert "https://helios.internal.net" in content

        # CRITICAL ZERO-LEAK CHECK: The actual secret key must NEVER be printed!
        assert "super-secret-production-token-999" not in content

        # It must instruct the agent to ask the user
        assert "<YOUR_HELIOS_API_KEY>" in content
        assert "Authentication Required" in content

        # 2. When query param ?token= supplied by user, it is safely rendered in snippets
        res_with_token = client.get(
            "/setup?token=user-client-token-abc",
            headers={"Host": "helios.example.com", "X-Forwarded-Proto": "https"},
        )
        assert res_with_token.status_code == 200
        assert "user-client-token-abc" in res_with_token.text
        assert "https://helios.example.com/sse?token=user-client-token-abc" in res_with_token.text


def test_get_client_setup_bundle_tool():
    # 1. Default (all, auto, workstation)
    bundle_all = get_client_setup_bundle()
    assert "Antigravity" in bundle_all
    assert "Cursor" in bundle_all
    assert "Claude-desktop" in bundle_all
    assert "Claude-code" in bundle_all
    assert "GEMINI.md" in bundle_all
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
    assert "Helios has been uninstalled" in bundle_uninstall

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
