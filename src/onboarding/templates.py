"""Global directive, skill, and cognitive guard hook script templates."""

from src import __version__
from src.config import get_word_limit


def generate_global_directive(
    instance_role: str = "workstation",
    word_limit: int | None = None,
    version: str | None = None,
) -> str:
    """
    Generate the global agent directive template (GEMINI.md / CLAUDE.md / AGENTS.md / global_rules.md / .cursor/rules/helios.mdc)
    wrapped in explicit <!-- HELIOS:START --> and <!-- HELIOS:END --> markers.
    """
    role = instance_role.strip().lower()
    limit = word_limit if word_limit is not None else get_word_limit()
    ver = (version or __version__).strip().lstrip("v")

    if role == "server-cli":
        body = (
            f"# Global Agent Directives — Helios Memory Protocol (Server CLI v{ver})\n\n"
            "You are connected to **Helios**, a centralized token-budgeted memory engine.\n\n"
            "## Mandatory Operating Rules:\n"
            f"1. **Pre-Flight Memory Check**: Always call `recall_memories(scope=\"<repo_or_dir>\", directive_version=\"{ver}\")` at the beginning of any session or task.\n"
            f"   - If modifying infrastructure, docker compose stacks, or system services, also check `recall_memories(scope=\"homelab\", directive_version=\"{ver}\")`.\n"
            "2. **Configuration Drift Check**: If investigating past parameter values or regressions, call `recall_history(scope=\"<repo>\")`.\n"
            "3. **Stale Memory Protocol**: When a memory is marked `[STALE]`, inspect its referenced `anchor_files`:\n"
            "   - If verified still accurate: call `revalidate_memories(memory_ids=[<id>])`.\n"
            "   - If changed: call `save_memory(scope=..., category='fact', content=..., subject='...')` to supersede it.\n"
            f"4. **AUDN Write Gate & Token Diet**:\n"
            f"   - Facts MUST be atomic and **<= {limit} words**. Omit filler words.\n"
            "   - Category must be one of: `'rule'` (guardrails), `'fact'` (architecture/ports), `'preference'` (style), `'episodic'` (temporary 14d notes).\n"
            "   - Never store host-local client setup states or local dotfile edits in shared repository scopes.\n"
            "5. **Terminal Token Diet & Noise Suppression (Headless Host)**:\n"
            "   - Never run unbounded logs or verbose test runners. Always use `docker logs --tail=50`, `journalctl -n 40 --no-pager`, and `git status -s`.\n"
            "   - For tests & builds: Always use quiet flags and short tracebacks (`pytest -q --tb=short --maxfail=2`, `npm test -- --silent`, `cargo test -- -q`, `docker build -q`, `pip install -q`).\n"
            "   - Generate targeted unified diffs or minimal block replacements rather than entire redundant files.\n"
            "6. **Write-Through Memory Capture (Definition of Done)**:\n"
            "   - Any infrastructure change, docker stack deployment, port allocation, repo movement, CI/CD setup, or non-obvious operational bug fix is **STRICTLY INCOMPLETE** until persisted to Helios via `save_memory()`.\n"
            "   - Never defer memory capture to session end or wait for user prompting. Persist changes immediately upon verifying them.\n"
            "7. **Periodic Distillation Audit**:\n"
            "   - Run the `/remember` skill or audit memories before context compaction or upon concluding a major milestone to prune obsolete facts (`deprecate_memory`) and ensure slot alignment.\n"
            "8. **Client Lifecycle & Uninstallation**:\n"
            "   - If the user requests to switch machine roles or uninstall Helios (\"uninstall helios\"), call `get_client_setup_bundle(action='switch_role'|'uninstall')` and execute the instructions."
        )
    else:
        # Workstation / IDE environment (default)
        body = (
            f"# Global Agent Directives — Helios Memory Protocol (v{ver})\n\n"
            "You are connected to **Helios**, a centralized token-budgeted memory engine.\n\n"
            "## Mandatory Operating Rules:\n"
            f"1. **Pre-Flight Memory Check**: Always call `recall_memories(scope=\"<current_repo_or_project>\", directive_version=\"{ver}\")` at the start of any conversation or task.\n"
            "2. **Stale Memory Protocol**: When a memory is flagged `[STALE]`, inspect the referenced `anchor_files` before relying on it:\n"
            "   - If still accurate: call `revalidate_memories(memory_ids=[<id>])`.\n"
            "   - If updated: call `save_memory(scope=..., category='fact', content=..., subject='...')`.\n"
            "3. **Write-Through Memory Capture (Definition of Done)**: When adding dependencies, changing ports, establishing conventions, modifying schemas, or fixing non-obvious bugs, persist them immediately with `save_memory()`. A task is incomplete until its architectural delta is recorded. Never store host-local client setup states or local dotfile edits in shared repository scopes.\n"
            f"4. **AUDN Write Gate**: Keep facts atomic and **<= {limit} words**. Omit conversational filler. Never store API secrets or bulky code dumps.\n"
            "5. **Terminal Token Diet & Noise Suppression**:\n"
            "   - For tests: Always use quiet flags and short tracebacks (`pytest -q --tb=short --maxfail=2`, `npm test -- --silent`, `cargo test -- -q`). If all tests pass, report only the 1-line summary.\n"
            "   - For builds & git: Use quiet flags (`docker build -q`, `npm i --silent --no-audit`, `pip install -q`, `git status -s`) and output targeted unified diffs or minimal block replacements rather than entire redundant files.\n"
            "6. **Periodic Distillation Audit**: Call the `/remember` skill or audit memories before clearing context or after major milestones to clean up obsolete entries.\n"
            "7. **Client Lifecycle & Uninstallation**: If the user requests to switch machine roles or uninstall Helios (\"uninstall helios\"), call `get_client_setup_bundle(action='switch_role'|'uninstall')` and execute the instructions."
        )

    return f"<!-- HELIOS:START -->\n{body}\n<!-- HELIOS:END -->"


def generate_remember_skill(word_limit: int | None = None) -> str:
    """Generate the ~/.gemini/skills/remember/SKILL.md skill definition."""
    limit = word_limit if word_limit is not None else get_word_limit()
    return (
        "---\n"
        "name: remember\n"
        "description: Distill durable architecture rules, changed ports, and bug learnings from the session into Helios before clearing context or after major milestones.\n"
        "---\n\n"
        "# Helios Remember Skill\n\n"
        "Use this skill for periodic distillation audits, before context compaction, or after major milestones to verify memory health.\n\n"
        "Note: Continuous state mutations (ports, stacks, bug fixes) should already be captured immediately via write-through `save_memory` calls.\n\n"
        "## Steps to Execute:\n"
        "1. **Analyze Session Learnings**: Identify any unpersisted ports, stack configs, bug fixes, or coding guardrails established in this conversation.\n"
        "2. **Check Existing Slots**: Call `recall_memories(scope=\"<current_scope>\")` to find existing subject slots.\n"
        "3. **Persist Updates**:\n"
        "   - To update a fact: `save_memory(scope=..., category='fact', content=..., subject='<slot_key>')` (automatically supersedes older records sharing slot).\n"
        "   - To set a coding guardrail: `save_memory(scope=..., category='rule', content=...)`.\n"
        "   - To revalidate an inspected stale fact: `revalidate_memories(memory_ids=[...])`.\n"
        "   - To archive an obsolete fact: `deprecate_memory(memory_id=..., reason=...)`.\n"
        f"4. **Word Limit**: Ensure all facts are atomic and `<={limit} words`.\n"
    )


def generate_guard_hook_script() -> str:
    """Generate the ~/.gemini/config/scripts/helios_guard.py hook script."""
    return '''#!/usr/bin/env python3
"""
Helios Write-Through Guard Hook for Antigravity (PreInvocation).

Inspects the recent conversation trajectory. If the agent performed workspace
or infrastructure mutations (file writes, edits, docker, git commits) without
invoking `helios.save_memory` via MCP, injects an ephemeral cognitive reminder
to enforce the Write-Through Definition of Done before finishing the turn.
"""

import json
import os
import re
import sys

MUTATING_TOOLS = {"edit_file", "write_file"}
MUTATING_COMMAND_PATTERNS = [
    r"\\bdocker\\s+(compose\\s+)?(up|run|restart|build|stop|rm)\\b",
    r"\\bgit\\s+(commit|push|rebase|merge|tag)\\b",
    r"\\bgh\\s+(repo|release|pr\\s+create|workflow)\\b",
    r"\\bsystemctl\\s+(start|stop|restart|enable)\\b",
]
CLIENT_CONFIG_IGNORE_PATTERNS = [
    r"(^|[\\\\/])\\.(gemini|cursor|claude|codex|codeium|windsurf|opencode|vscode|agents)([\\\\/]|$)",
    r"(^|[\\\\/])(GEMINI|CLAUDE|AGENTS)\\.md$",
    r"(^|[\\\\/])global_rules\\.md$",
    r"(^|[\\\\/])copilot-instructions\\.md$",
    r"(^|[\\\\/])(mcp|mcp_config|claude_desktop_config|opencode|hooks)\\.jsonc?$",
    r"(^|[\\\\/])config\\.toml$",
    r"(^|[\\\\/])helios_guard\\.py$",
    r"(^|[\\\\/])SKILL\\.md$",
]


def is_ignored_client_path(path: str, artifact_dir: str = "") -> bool:
    """Return True if path is inside artifact_dir or is a local AI client config/directive file."""
    if not path:
        return False
    if artifact_dir and path.startswith(artifact_dir):
        return True
    return any(re.search(pat, path, flags=re.IGNORECASE) for pat in CLIENT_CONFIG_IGNORE_PATTERNS)


def check_recent_trajectory(transcript_path: str, artifact_dir: str = "") -> bool:
    """Return True if recent steps contained unpersisted mutations."""
    if not transcript_path or not os.path.isfile(transcript_path):
        return False

    try:
        file_size = os.path.getsize(transcript_path)
        read_bytes = min(file_size, 40960)
        with open(transcript_path, "rb") as f:
            if file_size > read_bytes:
                f.seek(file_size - read_bytes)
            chunk = f.read().decode("utf-8", errors="ignore")

        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            return False

        has_mutation = False
        has_memory_capture = False

        for raw_line in reversed(lines[-20:]):
            try:
                step = json.loads(raw_line)
            except Exception:
                continue

            tool_calls = step.get("tool_calls", [])
            for tc in tool_calls:
                name = tc.get("name", "")
                args = tc.get("args", {})

                if name == "call_mcp_tool" and args.get("ServerName") == "helios":
                    tool_name = args.get("ToolName", "")
                    if tool_name in ("save_memory", "deprecate_memory", "revalidate_memories"):
                        has_memory_capture = True
                elif "helios_save_memory" in name:
                    has_memory_capture = True

                if name in MUTATING_TOOLS:
                    target_path = str(args.get("Path", ""))
                    if not is_ignored_client_path(target_path, artifact_dir):
                        has_mutation = True

                if name == "run_command":
                    cmd = str(args.get("CommandLine", ""))
                    for pat in MUTATING_COMMAND_PATTERNS:
                        if re.search(pat, cmd, flags=re.IGNORECASE):
                            has_mutation = True
                            break

        return has_mutation and not has_memory_capture
    except Exception:
        return False


def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print(json.dumps({"injectSteps": []}))
            return

        payload = json.loads(raw_input)
        transcript_path = payload.get("transcriptPath", "")
        artifact_dir = payload.get("artifactDirectoryPath", "")

        needs_nudge = check_recent_trajectory(transcript_path, artifact_dir)
        if needs_nudge:
            message = (
                "⚠️ HELIOS WRITE-THROUGH GUARD: You have executed workspace or infrastructure modifications. "
                "Remember: tasks are INCOMPLETE until persistent architectural changes, ports, or non-obvious fixes "
                "are recorded in Helios via helios.save_memory. Do not conclude your turn without persisting state."
            )
            output = {"injectSteps": [{"ephemeralMessage": message}]}
        else:
            output = {"injectSteps": []}

        print(json.dumps(output))
    except Exception:
        print(json.dumps({"injectSteps": []}))


if __name__ == "__main__":
    main()
'''


__all__ = [
    "generate_global_directive",
    "generate_guard_hook_script",
    "generate_remember_skill",
]
