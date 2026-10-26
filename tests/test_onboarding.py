import pytest
from starlette.testclient import TestClient

from src.onboarding import (
    generate_global_directive,
    generate_remember_skill,
    generate_setup_bash,
    generate_setup_markdown,
    generate_setup_powershell,
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
    assert "Write-Through Memory Capture" in workstation_directive
    assert "Before ending any session" not in workstation_directive
    assert "<= 25 words" in workstation_directive
    assert "docker logs --tail=50" not in workstation_directive

    # Test dynamic word limit injection
    custom_word_directive = generate_global_directive("workstation", word_limit=45)
    assert "<= 45 words" in custom_word_directive

    server_directive = generate_global_directive("server-cli")
    assert server_directive.startswith("<!-- HELIOS:START -->")
    assert server_directive.strip().endswith("<!-- HELIOS:END -->")
    assert "Pre-Flight Memory Check" in server_directive
    assert "Write-Through Memory Capture (Definition of Done)" in server_directive
    assert "Before ending any session" not in server_directive
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
        assert "https://helios.example.com/mcp?token=user-client-token-abc" in res_with_token.text


def test_http_setup_powershell_and_bash_endpoints(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "super-secret-auth-key-123")

    with TestClient(app) as client:
        # 1. PowerShell setup script endpoint (exempt from AuthGate)
        res_ps1 = client.get(
            "/setup.ps1",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "helios.mesh.net"},
        )
        assert res_ps1.status_code == 200
        ps1_text = res_ps1.text
        assert "Helios Automated Client Setup for Windows PowerShell" in ps1_text
        assert "https://helios.mesh.net/mcp" in ps1_text
        assert "mcp_config.json" in ps1_text
        assert "<!-- HELIOS:START -->" in ps1_text
        assert "super-secret-auth-key-123" not in ps1_text

        # 2. PowerShell script with user token query param
        res_ps1_token = client.get(
            "/setup.ps1?token=client-token-xyz",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "helios.mesh.net"},
        )
        assert res_ps1_token.status_code == 200
        assert "https://helios.mesh.net/mcp?token=client-token-xyz" in res_ps1_token.text

        # 3. Bash setup script endpoint (exempt from AuthGate)
        res_sh = client.get(
            "/setup.sh",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "helios.mesh.net"},
        )
        assert res_sh.status_code == 200
        sh_text = res_sh.text
        assert "#!/usr/bin/env bash" in sh_text
        assert "https://helios.mesh.net/mcp" in sh_text
        assert "mcp_config.json" in sh_text
        assert "<!-- HELIOS:START -->" in sh_text
        assert "super-secret-auth-key-123" not in sh_text


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


def test_setup_scripts_backtick_and_injection_safety():
    # 1. PowerShell setup script uses single-quoted literal here-strings
    ps_script = generate_setup_powershell("https://helios.example.com", query_token="my-token+123")
    assert "$directiveText = @'" in ps_script
    assert "'@" in ps_script
    assert "$skillText = @'" in ps_script
    assert "[regex]::Replace($content, '(?s)<!-- HELIOS:START -->.*?<!-- HELIOS:END -->', { param($m) $directiveText })" in ps_script
    # Ensure backticks in directives are present verbatim and not stripped
    assert "`anchor_files`" in ps_script
    assert "recall_memories(" in ps_script

    # 2. Bash setup script uses single-quoted heredocs and python env pass-through
    sh_script = generate_setup_bash("https://helios.example.com", query_token="my-token+123")
    assert "cat <<'HELIOS_DIRECTIVE_EOF'" in sh_script
    assert "cat <<'HELIOS_SKILL_EOF'" in sh_script
    assert "python3 - <<'PYEOF'" in sh_script
    assert "lambda _: directive" in sh_script
    assert "`anchor_files`" in sh_script
    assert "recall_memories(" in sh_script


def test_resolve_server_base_url_proxy_chains_and_token_encoding():
    # Multi-hop proxy headers
    headers = {
        "X-Forwarded-Proto": "https, http",
        "X-Forwarded-Host": "helios.internal.mesh:8443, reverse-proxy:8000",
    }
    resolved = resolve_server_base_url(headers)
    assert resolved == "https://helios.internal.mesh:8443"

    # Token URL-encoding in setup markdown 1-liners
    md = generate_setup_markdown("https://helios.internal.mesh:8443", query_token="sec+ret/token=123")
    assert "token=sec%2Bret%2Ftoken%3D123" in md
    assert "https://helios.internal.mesh:8443/setup.ps1?token=sec%2Bret%2Ftoken%3D123" in md
    assert "https://helios.internal.mesh:8443/setup.sh?token=sec%2Bret%2Ftoken%3D123" in md


def test_setup_scripts_role_and_client_customization():
    # 1. Bash customization with server-cli role and cursor client
    sh = generate_setup_bash(
        "https://helios.example.com",
        instance_role="server-cli",
        client="cursor",
    )
    assert "role: server-cli" in sh
    assert "docker logs --tail=50" in sh
    assert "Cursor MCP registered" in sh
    assert "Antigravity MCP registered" in sh

    # 2. PowerShell customization with server-cli role and cursor client
    ps = generate_setup_powershell(
        "https://helios.example.com",
        instance_role="server-cli",
        client="cursor",
    )
    assert "role: server-cli" in ps
    assert "docker logs --tail=50" in ps
    assert "Cursor MCP registered" in ps
    assert "Antigravity MCP registered" in ps
