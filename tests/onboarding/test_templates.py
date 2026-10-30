"""Unit tests for onboarding templates (global directives, remember skill, guard hook)."""

from src import __version__
from src.onboarding.templates import (
    generate_global_directive,
    generate_remember_skill,
)


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
