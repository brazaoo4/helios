"""Unit tests for client configuration paths, snippets, URL resolution, and OS platform normalization."""

from src.onboarding.bundles import generate_setup_markdown
from src.onboarding.client_config import (
    get_directive_path,
    get_mcp_config_path,
    get_mcp_config_snippet,
    normalize_os_platform,
    resolve_server_base_url,
)


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
    assert "[mcp_servers.helios]" in codex_toml
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
