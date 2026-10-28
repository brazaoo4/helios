import json
import pytest
from starlette.testclient import TestClient

from src import __version__
from src.onboarding import (
    generate_global_directive,
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

    # Codex, Windsurf, VS Code, OpenCode paths
    assert get_mcp_config_path("codex", "linux") == "~/.codex/config.toml"
    assert get_mcp_config_path("codex", "windows") == r"%USERPROFILE%\.codex\config.toml"
    assert get_mcp_config_path("windsurf", "linux") == "~/.codeium/windsurf/mcp_config.json"
    assert get_mcp_config_path("windsurf", "windows") == r"%USERPROFILE%\.codeium\windsurf\mcp_config.json"
    assert get_mcp_config_path("vscode", "linux") == "~/.config/Code/User/mcp.json"
    assert get_mcp_config_path("vscode", "macos") == "~/Library/Application Support/Code/User/mcp.json"
    assert get_mcp_config_path("vscode", "windows") == r"%APPDATA%\Code\User\mcp.json"
    assert get_mcp_config_path("opencode", "linux") == "~/.config/opencode/opencode.json"
    assert get_mcp_config_path("opencode", "windows") == r"%USERPROFILE%\.config\opencode\opencode.json"

    # Directive paths
    assert get_directive_path("antigravity", "linux") == "~/.gemini/config/GEMINI.md"
    assert get_directive_path("cursor", "linux") == "~/.cursor/rules/helios.mdc"
    assert get_directive_path("claude-code", "linux") == "~/.claude/CLAUDE.md"
    assert get_directive_path("codex", "linux") == "~/.codex/AGENTS.md"
    assert get_directive_path("windsurf", "linux") == "~/.codeium/windsurf/memories/global_rules.md"
    assert get_directive_path("vscode", "linux") == "~/.github/copilot-instructions.md"
    assert get_directive_path("opencode", "linux") == "~/.config/opencode/AGENTS.md"

    # Snippets
    anti_cfg = get_mcp_config_snippet("antigravity", "https://helios.example.com")
    assert isinstance(anti_cfg, dict)
    assert anti_cfg["mcpServers"]["helios"]["url"] == "https://helios.example.com/mcp"

    claude_cfg = get_mcp_config_snippet("claude-desktop", "https://helios.example.com", token="tok123")
    assert isinstance(claude_cfg, dict)
    assert claude_cfg["mcpServers"]["helios"]["args"] == ["-y", "mcp-remote", "https://helios.example.com/sse?token=tok123"]

    cli_cmd = get_mcp_config_snippet("claude-code", "https://helios.example.com")
    assert cli_cmd == "claude mcp add --transport sse helios https://helios.example.com/sse"

    codex_toml = get_mcp_config_snippet("codex", "https://helios.example.com", token="tok123")
    assert isinstance(codex_toml, str)
    assert '[mcp_servers.helios]' in codex_toml
    assert 'url = "https://helios.example.com/mcp?token=tok123"' in codex_toml

    windsurf_cfg = get_mcp_config_snippet("windsurf", "https://helios.example.com")
    assert isinstance(windsurf_cfg, dict)
    assert windsurf_cfg["mcpServers"]["helios"]["serverUrl"] == "https://helios.example.com/mcp"

    vscode_cfg = get_mcp_config_snippet("vscode", "https://helios.example.com")
    assert isinstance(vscode_cfg, dict)
    assert vscode_cfg["servers"]["helios"] == {"type": "http", "url": "https://helios.example.com/mcp"}

    opencode_cfg = get_mcp_config_snippet("opencode", "https://helios.example.com")
    assert isinstance(opencode_cfg, dict)
    assert opencode_cfg["mcp"]["helios"] == {
        "type": "remote",
        "url": "https://helios.example.com/mcp",
        "enabled": True,
    }


def test_global_directive_roles():
    workstation_directive = generate_global_directive("workstation")
    assert workstation_directive.startswith("<!-- HELIOS:START -->")
    assert workstation_directive.strip().endswith("<!-- HELIOS:END -->")
    assert f'directive_version="{__version__}"' in workstation_directive
    assert f"(v{__version__})" in workstation_directive
    assert "Never store host-local client setup states" in workstation_directive
    assert "Pre-Flight Memory Check" in workstation_directive
    assert "Write-Through Memory Capture" in workstation_directive
    assert "Before ending any session" not in workstation_directive
    assert "<= 25 words" in workstation_directive
    assert "Terminal Token Diet & Noise Suppression" in workstation_directive
    assert "pytest -q --tb=short --maxfail=2" in workstation_directive
    assert "docker build -q" in workstation_directive
    assert "git status -s" in workstation_directive
    assert "docker logs --tail=50" not in workstation_directive
    assert "journalctl -n 40 --no-pager" not in workstation_directive

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
    assert "Terminal Token Diet & Noise Suppression (Headless Host)" in server_directive
    assert "docker logs --tail=50" in server_directive
    assert "journalctl -n 40 --no-pager" in server_directive
    assert "pytest -q --tb=short --maxfail=2" in server_directive
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


def test_setup_scripts_backtick_and_injection_safety():
    # 1. PowerShell setup script uses single-quoted literal here-strings
    ps_script = generate_setup_powershell("https://helios.example.com", query_token="my-token+123")
    assert "$directiveText = @'" in ps_script
    assert "'@" in ps_script
    assert "$skillText = @'" in ps_script
    assert "[regex]::Replace($content, '(?s)<!-- HELIOS:START(?:\\s+[^>]+)? -->.*?<!-- HELIOS:END -->', { param($m) $directiveText })" in ps_script
    # Ensure backticks in directives are present verbatim and not stripped
    assert "`anchor_files`" in ps_script
    assert "recall_memories(" in ps_script
    assert "OpenAI Codex MCP registered" in ps_script
    assert "Windsurf MCP registered" in ps_script
    assert "VS Code MCP registered" in ps_script
    assert "OpenCode MCP registered" in ps_script

    # 2. Bash setup script uses single-quoted heredocs and python env pass-through
    sh_script = generate_setup_bash("https://helios.example.com", query_token="my-token+123")
    assert "cat <<'HELIOS_DIRECTIVE_EOF'" in sh_script
    assert "cat <<'HELIOS_SKILL_EOF'" in sh_script
    assert "python3 - <<'PYEOF'" in sh_script
    assert "lambda _: directive" in sh_script
    assert "`anchor_files`" in sh_script
    assert "recall_memories(" in sh_script
    assert "OpenAI Codex MCP registered" in sh_script
    assert "Windsurf MCP registered" in sh_script
    assert "VS Code MCP registered" in sh_script
    assert "OpenCode MCP registered" in sh_script


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


def test_http_uninstall_endpoints(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "super-secret-auth-key-123")

    with TestClient(app) as client:
        # 1. /uninstall (markdown guide)
        res_ui = client.get(
            "/uninstall",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "helios.mesh.net"},
        )
        assert res_ui.status_code == 200
        assert "Helios Client Uninstallation Guide" in res_ui.text
        assert "curl -fsSL https://helios.mesh.net/uninstall.sh | bash" in res_ui.text

        # 2. /uninstall.sh (bash script)
        res_sh = client.get("/uninstall.sh")
        assert res_sh.status_code == 200
        assert "#!/usr/bin/env bash" in res_sh.text
        assert "Uninstalling Helios client configuration" in res_sh.text
        assert "helios-write-through-guard" in res_sh.text
        assert "super-secret-auth-key-123" not in res_sh.text

        # 3. /uninstall.ps1 (powershell script)
        res_ps1 = client.get("/uninstall.ps1")
        assert res_ps1.status_code == 200
        assert "Helios Automated Client Uninstaller for Windows PowerShell" in res_ps1.text
        assert "helios-write-through-guard" in res_ps1.text

        # Verify generate_uninstall_powershell helper output directly
        ps_direct = generate_uninstall_powershell(client="cursor")
        assert 'client: cursor' in ps_direct
        assert 'Remove-HeliosDirective' in ps_direct


def test_bash_uninstall_execution_cleans_helios_and_preserves_user_configs(tmp_path, monkeypatch):
    import subprocess

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    # Pre-populate user configurations with Helios + custom user settings
    gemini_cfg = fake_home / ".gemini" / "config"
    gemini_cfg.mkdir(parents=True)

    # 1. mcp_config.json with helios and custom user server
    mcp_file = gemini_cfg / "mcp_config.json"
    mcp_file.write_text(
        json.dumps({
            "mcpServers": {
                "user-database": {"url": "http://localhost:5432/mcp"},
                "helios": {"url": "https://helios.example.com/mcp"},
            }
        })
    )

    # 2. GEMINI.md with user rules outside Helios markers
    gemini_md = gemini_cfg / "GEMINI.md"
    gemini_md.write_text(
        "# Custom User Rules\nAlways write clean code.\n\n"
        "<!-- HELIOS:START -->\n# Helios Directives\npre-flight check\n<!-- HELIOS:END -->\n\n"
        "## Additional User Guidelines\nEnd of turn.\n"
    )

    # 3. hooks.json with helios guard hook and user hook
    hooks_file = gemini_cfg / "hooks.json"
    hooks_file.write_text(
        json.dumps({
            "user-linter": {"PreInvocation": [{"command": "echo lint"}]},
            "helios-write-through-guard": {"PreInvocation": [{"command": "python3 guard.py"}]},
        })
    )

    # 4. Guard script and skill files
    guard_script = gemini_cfg / "scripts" / "helios_guard.py"
    guard_script.parent.mkdir(parents=True)
    guard_script.write_text("print('guard')")

    skill_file = fake_home / ".gemini" / "skills" / "remember" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("name: remember")

    # 5. Cursor rules (.mdc) that only contains Helios directive
    cursor_dir = fake_home / ".cursor"
    cursor_rules = cursor_dir / "rules"
    cursor_rules.mkdir(parents=True)
    helios_mdc = cursor_rules / "helios.mdc"
    helios_mdc.write_text("<!-- HELIOS:START -->\n# Helios\n<!-- HELIOS:END -->\n")

    # 6. Codex config.toml with user server and helios server
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    codex_toml = codex_dir / "config.toml"
    codex_toml.write_text(
        "[mcp_servers.my_custom_server]\nurl = \"http://local:9000\"\n\n"
        "[mcp_servers.helios]\nurl = \"https://helios.example.com/mcp\"\n"
    )

    # Run generated bash uninstaller
    sh_content = generate_uninstall_bash("https://helios.example.com", client="all")
    script_path = tmp_path / "uninstall.sh"
    script_path.write_text(sh_content)

    proc = subprocess.run(["bash", str(script_path)], capture_output=True, text=True, check=True)
    assert proc.returncode == 0

    # Verify MCP server was cleanly removed, but user-database preserved
    mcp_data = json.loads(mcp_file.read_text())
    assert "helios" not in mcp_data["mcpServers"]
    assert "user-database" in mcp_data["mcpServers"]

    # Verify GEMINI.md preserved user rules and stripped Helios block
    g_text = gemini_md.read_text()
    assert "# Custom User Rules" in g_text
    assert "Always write clean code." in g_text
    assert "## Additional User Guidelines" in g_text
    assert "HELIOS:START" not in g_text
    assert "HELIOS:END" not in g_text

    # Verify hooks.json preserved user-linter and removed helios guard
    hooks_data = json.loads(hooks_file.read_text())
    assert "helios-write-through-guard" not in hooks_data
    assert "user-linter" in hooks_data

    # Verify guard script, skill directory, and empty .mdc were deleted
    assert not guard_script.exists()
    assert not skill_file.exists()
    assert not (fake_home / ".gemini" / "skills" / "remember").exists()
    assert not helios_mdc.exists()

    # Verify Codex config.toml preserved custom server
    c_text = codex_toml.read_text()
    assert "[mcp_servers.my_custom_server]" in c_text
    assert "[mcp_servers.helios]" not in c_text

