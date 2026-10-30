"""Unit and execution tests for generated uninstaller scripts."""

import json
import subprocess

from src.onboarding.scripts_uninstall import generate_uninstall_bash


def test_bash_uninstall_execution_cleans_helios_and_preserves_user_configs(tmp_path, monkeypatch):
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
        '[mcp_servers.my_custom_server]\nurl = "http://local:9000"\n\n[mcp_servers.helios]\nurl = "https://helios.example.com/mcp"\n'
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
