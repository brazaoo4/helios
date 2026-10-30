"""Unit and execution tests for generated setup scripts (Bash and PowerShell)."""

import json
import subprocess

from src.onboarding.scripts_setup import (
    generate_setup_bash,
    generate_setup_powershell,
)


def test_setup_scripts_backtick_and_injection_safety():
    # 1. PowerShell setup script uses single-quoted literal here-strings
    ps_script = generate_setup_powershell("https://helios.example.com", query_token="my-token+123")
    assert "$directiveText = @'" in ps_script
    assert "'@" in ps_script
    assert "$skillText = @'" in ps_script
    assert (
        "[regex]::Replace($content, '(?s)<!-- HELIOS:START(?:\\s+[^>]+)? -->.*?<!-- HELIOS:END -->', { param($m)"
        " $directiveText })" in ps_script
    )
    # Ensure backticks in directives are present verbatim and not stripped
    assert "`anchor_files`" in ps_script
    assert "recall_memories(" in ps_script
    assert "OpenAI Codex MCP registered" in ps_script
    assert "Windsurf MCP registered" in ps_script
    assert "VS Code MCP registered" in ps_script
    assert "OpenCode MCP registered" in ps_script

    # 2. Bash setup script uses single-quoted heredocs and python args pass-through
    sh_script = generate_setup_bash("https://helios.example.com", query_token="my-token+123")
    assert "cat <<'HELIOS_DIRECTIVE_EOF'" in sh_script
    assert "cat <<'HELIOS_SKILL_EOF'" in sh_script
    assert "python3 - " in sh_script
    assert "<<'PYEOF'" in sh_script
    assert "lambda _: directive" in sh_script
    assert "`anchor_files`" in sh_script
    assert "recall_memories(" in sh_script
    assert "OpenAI Codex MCP registered" in sh_script
    assert "Windsurf MCP registered" in sh_script
    assert "VS Code MCP registered" in sh_script
    assert "OpenCode MCP registered" in sh_script


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


def test_bash_setup_execution_in_temp_home(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    # Pre-create client directories to test auto-detection and multi-client configuration
    (fake_home / ".codex").mkdir(parents=True)
    (fake_home / ".codeium" / "windsurf").mkdir(parents=True)
    (fake_home / ".config" / "opencode").mkdir(parents=True)

    # Verify no os.environ or os.getenv in the generated script
    sh_script = generate_setup_bash("https://helios.example.com", client="all")
    assert "os.environ" not in sh_script
    assert "os.getenv" not in sh_script

    # Execute generated setup script in temporary HOME
    script_path = tmp_path / "setup.sh"
    script_path.write_text(sh_script, encoding="utf-8")

    proc = subprocess.run(["bash", str(script_path)], capture_output=True, text=True, check=True)
    assert proc.returncode == 0

    # 1. Antigravity MCP config & directive & remember skill & guard hook
    gemini_cfg = fake_home / ".gemini" / "config"
    mcp_file = gemini_cfg / "mcp_config.json"
    assert mcp_file.exists()
    mcp_data = json.loads(mcp_file.read_text(encoding="utf-8"))
    assert mcp_data["mcpServers"]["helios"]["url"] == "https://helios.example.com/mcp"

    gemini_md = gemini_cfg / "GEMINI.md"
    assert gemini_md.exists()
    assert "<!-- HELIOS:START -->" in gemini_md.read_text(encoding="utf-8")

    skill_file = fake_home / ".gemini" / "skills" / "remember" / "SKILL.md"
    assert skill_file.exists()
    assert "name: remember" in skill_file.read_text(encoding="utf-8")

    guard_script = gemini_cfg / "scripts" / "helios_guard.py"
    assert guard_script.exists()

    hooks_file = gemini_cfg / "hooks.json"
    assert hooks_file.exists()
    hooks_data = json.loads(hooks_file.read_text(encoding="utf-8"))
    assert "helios-write-through-guard" in hooks_data

    # 2. Cursor MCP & directive rule
    cursor_mcp = fake_home / ".cursor" / "mcp.json"
    assert cursor_mcp.exists()
    cursor_data = json.loads(cursor_mcp.read_text(encoding="utf-8"))
    assert cursor_data["mcpServers"]["helios"]["url"] == "https://helios.example.com/sse"

    cursor_rule = fake_home / ".cursor" / "rules" / "helios.mdc"
    assert cursor_rule.exists()
    assert "<!-- HELIOS:START -->" in cursor_rule.read_text(encoding="utf-8")

    # 3. Codex config.toml & AGENTS.md
    codex_toml = fake_home / ".codex" / "config.toml"
    assert codex_toml.exists()
    assert "[mcp_servers.helios]" in codex_toml.read_text(encoding="utf-8")
    assert (fake_home / ".codex" / "AGENTS.md").exists()

    # 4. Windsurf config & global_rules.md
    windsurf_mcp = fake_home / ".codeium" / "windsurf" / "mcp_config.json"
    assert windsurf_mcp.exists()
    assert (fake_home / ".codeium" / "windsurf" / "memories" / "global_rules.md").exists()

    # 5. OpenCode opencode.json & AGENTS.md
    opencode_json = fake_home / ".config" / "opencode" / "opencode.json"
    assert opencode_json.exists()
    assert (fake_home / ".config" / "opencode" / "AGENTS.md").exists()
