"""
Helios AI-Driven Client Onboarding Module.

Generates structured installation instructions, non-destructive MCP configs,
global agent directives (GEMINI.md / CLAUDE.md / AGENTS.md / global_rules.md / .cursor/rules)
with idempotent <!-- HELIOS:START --> markers, and the /remember skill for Antigravity, Cursor,
Claude Desktop, Claude Code, OpenAI Codex CLI, Windsurf, VS Code / GitHub Copilot, and OpenCode
across Windows, Linux, and macOS.
"""

import json
import re
import sys
import urllib.parse
from typing import Any

from src import __version__
from src.config import get_api_key, get_public_url, get_word_limit

SUPPORTED_CLIENTS: tuple[str, ...] = (
    "antigravity",
    "cursor",
    "claude-desktop",
    "claude-code",
    "codex",
    "windsurf",
    "vscode",
    "opencode",
)


def resolve_server_base_url(headers: dict[str, str] | None = None) -> str:
    """
    Dynamically resolve the Helios server's base URL.
    1. HELIOS_PUBLIC_URL override if configured.
    2. Incoming request headers (X-Forwarded-Proto + X-Forwarded-Host / Host).
    3. Fallback to http://localhost:8000.
    """
    pub = get_public_url()
    if pub:
        return pub.rstrip("/")

    if headers:
        norm_headers = {str(k).lower(): str(v) for k, v in headers.items()}
        raw_proto = norm_headers.get("x-forwarded-proto", "http")
        proto = raw_proto.split(",")[0].strip().lower()
        if proto not in ("http", "https"):
            proto = "http"

        raw_host = norm_headers.get("x-forwarded-host") or norm_headers.get("host") or "localhost:8000"
        host = raw_host.split(",")[0].strip()
        host = re.sub(r"""["'`\s;]""", "", host)
        if not host:
            host = "localhost:8000"

        return f"{proto}://{host}".rstrip("/")

    return "http://localhost:8000"


def normalize_os_platform(os_platform: str = "auto") -> str:
    """Normalize OS platform ('windows', 'linux', 'macos')."""
    p = os_platform.strip().lower()
    if p in ("windows", "win", "win32"):
        return "windows"
    elif p in ("darwin", "macos", "mac", "osx"):
        return "macos"
    elif p in ("linux", "ubuntu", "debian"):
        return "linux"

    if sys.platform.startswith("win"):
        return "windows"
    elif sys.platform == "darwin":
        return "macos"
    return "linux"


def get_mcp_config_path(client: str, os_platform: str = "auto") -> str:
    """Return the standard MCP config file path for the client and OS."""
    c = client.strip().lower()
    plat = normalize_os_platform(os_platform)

    if c == "antigravity":
        if plat == "windows":
            return r"%USERPROFILE%\.gemini\config\mcp_config.json"
        return "~/.gemini/config/mcp_config.json"
    elif c == "cursor":
        if plat == "windows":
            return r"%USERPROFILE%\.cursor\mcp.json"
        return "~/.cursor/mcp.json"
    elif c == "claude-desktop":
        if plat == "windows":
            return r"%APPDATA%\Claude\claude_desktop_config.json"
        elif plat == "macos":
            return "~/Library/Application Support/Claude/claude_desktop_config.json"
        return "~/.config/Claude/claude_desktop_config.json"
    elif c == "claude-code":
        return "CLI command (`claude mcp add`)"
    elif c == "codex":
        if plat == "windows":
            return r"%USERPROFILE%\.codex\config.toml"
        return "~/.codex/config.toml"
    elif c == "windsurf":
        if plat == "windows":
            return r"%USERPROFILE%\.codeium\windsurf\mcp_config.json"
        return "~/.codeium/windsurf/mcp_config.json"
    elif c == "vscode":
        if plat == "windows":
            return r"%APPDATA%\Code\User\mcp.json"
        elif plat == "macos":
            return "~/Library/Application Support/Code/User/mcp.json"
        return "~/.config/Code/User/mcp.json"
    elif c == "opencode":
        if plat == "windows":
            return r"%USERPROFILE%\.config\opencode\opencode.json"
        return "~/.config/opencode/opencode.json"
    return "~/.mcp/config.json"


def get_directive_path(client: str, os_platform: str = "auto") -> str:
    """Return the standard global directive/instructions file path for the client and OS."""
    c = client.strip().lower()
    plat = normalize_os_platform(os_platform)

    if c == "antigravity":
        if plat == "windows":
            return r"%USERPROFILE%\.gemini\config\GEMINI.md"
        return "~/.gemini/config/GEMINI.md"
    elif c == "cursor":
        if plat == "windows":
            return r"%USERPROFILE%\.cursor\rules\helios.mdc"
        return "~/.cursor/rules/helios.mdc"
    elif c in ("claude-desktop", "claude-code"):
        if plat == "windows":
            return r"%USERPROFILE%\.claude\CLAUDE.md"
        return "~/.claude/CLAUDE.md"
    elif c == "codex":
        if plat == "windows":
            return r"%USERPROFILE%\.codex\AGENTS.md"
        return "~/.codex/AGENTS.md"
    elif c == "windsurf":
        if plat == "windows":
            return r"%USERPROFILE%\.codeium\windsurf\memories\global_rules.md"
        return "~/.codeium/windsurf/memories/global_rules.md"
    elif c == "vscode":
        if plat == "windows":
            return r"%USERPROFILE%\.github\copilot-instructions.md"
        return "~/.github/copilot-instructions.md"
    elif c == "opencode":
        if plat == "windows":
            return r"%USERPROFILE%\.config\opencode\AGENTS.md"
        return "~/.config/opencode/AGENTS.md"
    return "~/.gemini/config/GEMINI.md"


def get_mcp_config_snippet(
    client: str,
    base_url: str,
    token: str | None = None,
) -> dict[str, Any] | str:
    """Generate the exact JSON/TOML configuration block or CLI command for the client."""
    c = client.strip().lower()
    clean_base = base_url.rstrip("/")
    token_suffix = ""
    if token:
        clean_tok = token.strip()
        if clean_tok == "<YOUR_HELIOS_API_KEY>":
            token_suffix = f"?token={clean_tok}"
        else:
            token_suffix = f"?token={urllib.parse.quote(clean_tok, safe='')}"

    mcp_url = f"{clean_base}/mcp{token_suffix}"
    sse_url = f"{clean_base}/sse{token_suffix}"

    if c == "antigravity":
        return {
            "mcpServers": {
                "helios": {
                    "url": mcp_url,
                }
            }
        }
    elif c == "cursor":
        return {
            "mcpServers": {
                "helios": {
                    "url": sse_url,
                }
            }
        }
    elif c == "claude-desktop":
        return {
            "mcpServers": {
                "helios": {
                    "command": "npx",
                    "args": ["-y", "mcp-remote", sse_url],
                }
            }
        }
    elif c == "claude-code":
        return f"claude mcp add --transport sse helios {sse_url}"
    elif c == "codex":
        return f'[mcp_servers.helios]\nurl = "{mcp_url}"'
    elif c == "windsurf":
        return {
            "mcpServers": {
                "helios": {
                    "serverUrl": mcp_url,
                }
            }
        }
    elif c == "vscode":
        return {
            "servers": {
                "helios": {
                    "type": "http",
                    "url": mcp_url,
                }
            }
        }
    elif c == "opencode":
        return {
            "mcp": {
                "helios": {
                    "type": "remote",
                    "url": mcp_url,
                    "enabled": True,
                }
            }
        }
    else:
        return {
            "mcpServers": {
                "helios": {
                    "url": sse_url,
                }
            }
        }


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


def generate_client_bundle(
    client: str = "all",
    os_platform: str = "auto",
    instance_role: str = "workstation",
    base_url: str = "",
    action: str = "install_or_update",
) -> str:
    """
    Generate client setup payload for the get_client_setup_bundle MCP tool.
    Supports action='install_or_update', 'switch_role', or 'uninstall'.
    """
    act = (action or "install_or_update").strip().lower()
    plat = normalize_os_platform(os_platform)
    resolved_base = base_url or resolve_server_base_url()

    # --- Action: UNINSTALL ---
    if act == "uninstall":
        lines = [
            "# Helios Client Uninstallation Guide",
            f"- **Target Client**: `{client}`",
            f"- **OS Platform**: `{plat}`",
            "",
            "> [!TIP]",
            "> **Automated 1-Liner Uninstallation**:",
            f"> - Linux/macOS: `curl -fsSL {resolved_base}/uninstall.sh | bash` (or append `?client={client}`)",
            f"> - Windows (PowerShell): `irm {resolved_base}/uninstall.ps1 | iex` (or append `?client={client}`)",
            "",
            "To perform the removal manually or agent-driven, follow these steps:",
            "",
            "### 1. Remove MCP Server Entry",
        ]
        target_clients = list(SUPPORTED_CLIENTS) if client == "all" else [client]
        for c in target_clients:
            path = get_mcp_config_path(c, plat)
            if c == "claude-code":
                lines.append("- **Claude-code**: Run CLI command `claude mcp remove helios`")
            elif c == "codex":
                lines.append(f"- **Codex**: Run `codex mcp remove helios` or remove `[mcp_servers.helios]` from `{path}`.")
            elif c == "vscode":
                lines.append(f"- **Vscode**: Open `{path}` and remove the `\"helios\"` key under `\"servers\"`.")
            elif c == "opencode":
                lines.append(f"- **Opencode**: Open `{path}` and remove the `\"helios\"` key under `\"mcp\"`.")
            else:
                lines.append(f"- **{c.capitalize()}**: Open `{path}` and remove the `\"helios\"` key under `\"mcpServers\"`.")

        lines.extend([
            "",
            "### 2. Remove Global Directive Block",
            "In your global directive file (`GEMINI.md`, `CLAUDE.md`, `AGENTS.md`, `global_rules.md`, `copilot-instructions.md`, or `.cursor/rules/helios.mdc`),",
            "delete the section bounded by the Helios markers (including the markers):",
            "```markdown",
            "<!-- HELIOS:START -->",
            "... (delete everything between and including these markers) ...",
            "<!-- HELIOS:END -->",
            "```",
            "If the file only contained the Helios directive block, delete the file.",
            "",
            "### 3. Remove Write-Through Cognitive Guard Hook",
            "For Antigravity environments:",
            "- Remove the `\"helios-write-through-guard\"` entry from `~/.gemini/config/hooks.json`.",
            "- Delete `~/.gemini/config/scripts/helios_guard.py` (if present).",
            "",
            "### 4. Remove `/remember` Skill",
            "Delete the skill file and folder:",
            "- `~/.gemini/skills/remember` (or `~/.gemini/config/skills/remember`)",
            "",
            "### 5. Final Step",
            "Restart your active IDE window or agent session to flush loaded MCP tools and memory caches.",
            "Helios has been cleanly uninstalled from this client environment.",
        ])
        return "\n".join(lines)

    # --- Action: INSTALL / UPDATE / SWITCH_ROLE ---
    has_auth = get_api_key() is not None
    token_placeholder = "<YOUR_HELIOS_API_KEY>" if has_auth else None
    active_word_limit = get_word_limit()

    lines = [
        "# Helios Client Setup Bundle",
        f"- **Lifecycle Action**: `{act}`",
        f"- **Helios Base URL**: `{resolved_base}`",
        f"- **Authentication**: {'HELIOS_API_KEY required' if has_auth else 'Open Mode (No API key required)'}",
        f"- **Active Word Limit**: `{active_word_limit}` words",
        f"- **Target OS**: `{plat}`",
        f"- **Instance Role**: `{instance_role}`",
        "",
        "> [!IMPORTANT]",
        "> **Idempotent Update Rule**:",
        "> 1. In MCP config files, update/insert only the `\"helios\"` server block; preserve all other servers.",
        "> 2. In `GEMINI.md` / `CLAUDE.md` / `AGENTS.md` / `global_rules.md` / `.cursor/rules/helios.mdc`, if `<!-- HELIOS:START -->...<!-- HELIOS:END -->` already exists,",
        ">    replace only the content between those markers. Do NOT clobber other custom user instructions.",
        "",
        "---",
        "## 1. MCP Configuration",
        "",
    ]

    clients_to_show = list(SUPPORTED_CLIENTS) if client == "all" else [client]

    for c in clients_to_show:
        path = get_mcp_config_path(c, os_platform)
        dir_path = get_directive_path(c, os_platform)
        snippet = get_mcp_config_snippet(c, resolved_base, token_placeholder)
        lines.append(f"### {c.capitalize()}")
        lines.append(f"- **MCP Config Path**: `{path}`")
        lines.append(f"- **Global Directive Path**: `{dir_path}`")
        if isinstance(snippet, dict):
            lines.append("```json")
            lines.append(json.dumps(snippet, indent=2))
            lines.append("```")
        elif c == "codex":
            lines.append("```toml")
            lines.append(snippet)
            lines.append("```")
        else:
            lines.append("```bash")
            lines.append(snippet)
            lines.append("```")
        lines.append("")

    lines.extend([
        "---",
        "## 2. Global Agent Directive (`GEMINI.md` / `CLAUDE.md` / `AGENTS.md` / `global_rules.md` / `.cursor/rules/helios.mdc`)",
        "",
        "```markdown",
        generate_global_directive(instance_role, word_limit=active_word_limit).strip(),
        "```",
        "",
        "---",
        "## 3. `/remember` Skill (`~/.gemini/skills/remember/SKILL.md`)",
        "",
        "```markdown",
        generate_remember_skill(word_limit=active_word_limit).strip(),
        "```",
        "",
        "---",
        "## 4. Git Webhook Drift Tracking (`manage_git_webhooks`)",
        "",
        "Helios automatically tracks configuration drift when commits touch `anchor_files`.",
        "- Execute `manage_git_webhooks(action='list')` to audit candidate repositories and webhook statuses.",
        "- Present the repository checklist to the user and ask which repositories to enable.",
        "- Execute `manage_git_webhooks(action='enable', repos=[...])` to activate drift tracking.",
    ])

    return "\n".join(lines)


def generate_setup_markdown(
    base_url: str,
    has_auth: bool = False,
    query_token: str | None = None,
) -> str:
    """
    Generate self-contained setup prompt returned by GET /setup.
    Designed for AI agents fetching via `curl -fsSL https://<host>/setup`.
    """
    token_param = query_token if query_token else ("<YOUR_HELIOS_API_KEY>" if has_auth else "")
    token_suffix = ""
    if query_token and query_token.strip():
        token_suffix = f"?token={urllib.parse.quote(query_token.strip(), safe='')}"
    elif has_auth:
        token_suffix = "?token=<YOUR_HELIOS_API_KEY>"

    clean_base = base_url.rstrip("/")
    active_word_limit = get_word_limit()

    auth_notice = ""
    if has_auth and not query_token:
        auth_notice = (
            "> [!IMPORTANT]\n"
            "> **Authentication Required**: This Helios server requires `HELIOS_API_KEY`. "
            "Please ask the user for their Helios API key and replace `<YOUR_HELIOS_API_KEY>` "
            "in the MCP configuration URLs.\n\n"
        )
    elif query_token:
        auth_notice = (
            "> [!NOTE]\n"
            "> Authenticated session token detected and included in configuration snippets.\n\n"
        )

    return (
        f"# Helios AI-Driven Client Onboarding\n\n"
        f"You are configuring a local environment to connect to **Helios** at `{clean_base}`.\n\n"
        f"{auth_notice}"
        "## Instant 1-Liner Automated Setup:\n"
        "To configure your local environment in 1 second without manual file editing:\n\n"
        "- **Windows (PowerShell)**:\n"
        "  ```powershell\n"
        f"  irm {clean_base}/setup.ps1{token_suffix} | iex\n"
        "  ```\n\n"
        "- **Linux / macOS (Bash)**:\n"
        "  ```bash\n"
        f"  curl -fsSL {clean_base}/setup.sh{token_suffix} | bash\n"
        "  ```\n\n"
        "---\n\n"
        "## Instructions for the AI Agent (Manual File Configuration):\n"
        "If not executing the 1-liner automated script above, follow these steps:\n"
        "1. Detect the current operating system (Windows, Linux, macOS) and the active client/editor.\n"
        "2. Safely read and merge the `helios` server block into the appropriate MCP config file without clobbering existing servers.\n"
        "3. Configure the Global Agent Directive (`GEMINI.md`, `CLAUDE.md`, `AGENTS.md`, `global_rules.md`, or `.cursor/rules/helios.mdc`). "
        "If `<!-- HELIOS:START -->...<!-- HELIOS:END -->` already exists in the file, replace only that block, "
        "preserving all existing user rules.\n"
        "   - **Windows Note**: Files may use CRLF (`\\r\\n`) line endings and `GEMINI.md` may be a symlink. "
        "Use atomic script replacement or Python instead of exact-string multi-line matching to avoid newline mismatches.\n"
        "   - **PowerShell Note**: Always use `curl.exe -m 10` or `Invoke-RestMethod`, never bare `curl` which can hang on standard I/O.\n"
        "4. Install the `/remember` skill into `~/.gemini/skills/remember/SKILL.md`.\n"
        "5. **Interactive Git Drift Webhook Setup (Mandatory Follow-Up)**:\n"
        "   - After verifying the MCP connection, immediately call `manage_git_webhooks(action='list')` to audit repository webhooks.\n"
        "   - Present the repository checklist to the user and ask: *'Which of these repositories would you like to enable automated push drift tracking on?'*\n"
        "   - Call `manage_git_webhooks(action='enable', repos=[...])` for the repositories the user confirms.\n\n"
        "### MCP Client Configuration Files:\n\n"
        "#### Antigravity / Gemini CLI:\n"
        "- **Path (Linux/macOS)**: `~/.gemini/config/mcp_config.json` (Directive: `~/.gemini/config/GEMINI.md`)\n"
        "- **Path (Windows)**: `%USERPROFILE%\\.gemini\\config\\mcp_config.json`\n"
        "```json\n"
        + json.dumps(get_mcp_config_snippet("antigravity", clean_base, token_param or None), indent=2)
        + "\n```\n\n"
        "#### Cursor IDE:\n"
        "- **Path**: `~/.cursor/mcp.json` (or `%USERPROFILE%\\.cursor\\mcp.json` on Windows; Directive: `~/.cursor/rules/helios.mdc`)\n"
        "```json\n"
        + json.dumps(get_mcp_config_snippet("cursor", clean_base, token_param or None), indent=2)
        + "\n```\n\n"
        "#### Claude Desktop:\n"
        "- **Path (macOS)**: `~/Library/Application Support/Claude/claude_desktop_config.json`\n"
        "- **Path (Linux)**: `~/.config/Claude/claude_desktop_config.json`\n"
        "- **Path (Windows)**: `%APPDATA%\\Claude\\claude_desktop_config.json`\n"
        "```json\n"
        + json.dumps(get_mcp_config_snippet("claude-desktop", clean_base, token_param or None), indent=2)
        + "\n```\n\n"
        "#### Claude Code CLI:\n"
        "- **Directive Path**: `~/.claude/CLAUDE.md`\n"
        "```bash\n"
        + str(get_mcp_config_snippet("claude-code", clean_base, token_param or None))
        + "\n```\n\n"
        "#### OpenAI Codex CLI:\n"
        "- **Path**: `~/.codex/config.toml` (or `%USERPROFILE%\\.codex\\config.toml`; Directive: `~/.codex/AGENTS.md`)\n"
        "```toml\n"
        + str(get_mcp_config_snippet("codex", clean_base, token_param or None))
        + "\n```\n\n"
        "#### Windsurf (Codeium):\n"
        "- **Path**: `~/.codeium/windsurf/mcp_config.json` (Directive: `~/.codeium/windsurf/memories/global_rules.md`)\n"
        "```json\n"
        + json.dumps(get_mcp_config_snippet("windsurf", clean_base, token_param or None), indent=2)
        + "\n```\n\n"
        "#### VS Code / GitHub Copilot:\n"
        "- **Path (Linux)**: `~/.config/Code/User/mcp.json` | **macOS**: `~/Library/Application Support/Code/User/mcp.json` | **Windows**: `%APPDATA%\\Code\\User\\mcp.json`\n"
        "```json\n"
        + json.dumps(get_mcp_config_snippet("vscode", clean_base, token_param or None), indent=2)
        + "\n```\n\n"
        "#### OpenCode CLI:\n"
        "- **Path**: `~/.config/opencode/opencode.json` (Directive: `~/.config/opencode/AGENTS.md`)\n"
        "```json\n"
        + json.dumps(get_mcp_config_snippet("opencode", clean_base, token_param or None), indent=2)
        + "\n```\n\n"
        "### Global Directive Template:\n"
        "Save this in `GEMINI.md`, `CLAUDE.md`, `AGENTS.md`, `global_rules.md`, or `.cursor/rules/helios.mdc` (idempotently replacing existing `<!-- HELIOS:START -->` block):\n"
        "```markdown\n"
        + generate_global_directive("workstation", word_limit=active_word_limit).strip()
        + "\n```\n\n"
        "### `/remember` Skill (`~/.gemini/skills/remember/SKILL.md`):\n"
        "```markdown\n"
        + generate_remember_skill(word_limit=active_word_limit).strip()
        + "\n```\n"
    )


def generate_setup_powershell(
    base_url: str,
    query_token: str | None = None,
    instance_role: str = "workstation",
    client: str = "all",
) -> str:
    """
    Generate an automated, self-contained Windows PowerShell onboarding script.
    Usage: irm https://<host>/setup.ps1 | iex
    Handles NTFS symlinks, CRLF line endings, multi-client auto-detection, and idempotent marker replacement.
    """
    clean_base = base_url.rstrip("/")
    token_suffix = ""
    if query_token and query_token.strip():
        token_suffix = f"?token={urllib.parse.quote(query_token.strip(), safe='')}"
    mcp_url = f"{clean_base}/mcp{token_suffix}"
    sse_url = f"{clean_base}/sse{token_suffix}"
    active_limit = get_word_limit()
    directive = generate_global_directive(instance_role, word_limit=active_limit).strip()
    skill = generate_remember_skill(word_limit=active_limit).strip()
    role_norm = instance_role.strip().lower()
    client_norm = client.strip().lower()

    return f"""# Helios Automated Client Setup for Windows PowerShell
$ErrorActionPreference = 'Stop'
Write-Host "Configuring Helios client environment for {clean_base} (role: {role_norm})..." -ForegroundColor Cyan

$directiveText = @'
{directive}
'@

function Set-HeliosDirective {{
    param([string]$FilePath)
    $parentDir = Split-Path -Parent $FilePath
    if (-not (Test-Path $parentDir)) {{ New-Item -ItemType Directory -Path $parentDir -Force | Out-Null }}
    if (Test-Path $FilePath) {{
        $resolvedPath = (Resolve-Path $FilePath).Path
        $content = [System.IO.File]::ReadAllText($resolvedPath, [System.Text.Encoding]::UTF8)
        if ($content -match '(?s)<!-- HELIOS:START(?:\\s+[^>]+)? -->.*?<!-- HELIOS:END -->') {{
            $content = [regex]::Replace($content, '(?s)<!-- HELIOS:START(?:\\s+[^>]+)? -->.*?<!-- HELIOS:END -->', {{ param($m) $directiveText }})
        }} else {{
            $content = $directiveText + "`r`n`r`n" + $content
        }}
        [System.IO.File]::WriteAllText($resolvedPath, $content, [System.Text.Encoding]::UTF8)
    }} else {{
        [System.IO.File]::WriteAllText($FilePath, $directiveText, [System.Text.Encoding]::UTF8)
    }}
}}

# 1. Antigravity MCP Configuration (~/.gemini/config/mcp_config.json)
$configDir = Join-Path $env:USERPROFILE ".gemini\\config"
if (-not (Test-Path $configDir)) {{ New-Item -ItemType Directory -Path $configDir -Force | Out-Null }}
$mcpConfigPath = Join-Path $configDir "mcp_config.json"

$mcpData = @{{ mcpServers = @{{}} }}
if (Test-Path $mcpConfigPath) {{
    try {{
        $existing = Get-Content -Path $mcpConfigPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
        if ($existing -and $existing.ContainsKey("mcpServers")) {{
            $mcpData = $existing
        }}
    }} catch {{
        Write-Warning "Could not parse existing mcp_config.json; initializing fresh server map."
    }}
}}
if (-not $mcpData.ContainsKey("mcpServers") -or $null -eq $mcpData.mcpServers) {{
    $mcpData.mcpServers = @{{}}
}}
$mcpData.mcpServers["helios"] = @{{ url = "{mcp_url}" }}
$mcpJson = $mcpData | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($mcpConfigPath, $mcpJson, [System.Text.Encoding]::UTF8)
Write-Host "  [OK] Antigravity MCP registered in $mcpConfigPath" -ForegroundColor Green

# 2. Cursor MCP Configuration (if %USERPROFILE%\\.cursor exists or client is cursor/all)
$cursorDir = Join-Path $env:USERPROFILE ".cursor"
if ((Test-Path $cursorDir) -or "{client_norm}" -eq "cursor" -or "{client_norm}" -eq "all") {{
    if (-not (Test-Path $cursorDir)) {{ New-Item -ItemType Directory -Path $cursorDir -Force | Out-Null }}
    $cursorMcpPath = Join-Path $cursorDir "mcp.json"
    $cursorData = @{{ mcpServers = @{{}} }}
    if (Test-Path $cursorMcpPath) {{
        try {{
            $cExisting = Get-Content -Path $cursorMcpPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($cExisting -and $cExisting.ContainsKey("mcpServers")) {{ $cursorData = $cExisting }}
        }} catch {{}}
    }}
    if (-not $cursorData.ContainsKey("mcpServers") -or $null -eq $cursorData.mcpServers) {{ $cursorData.mcpServers = @{{}} }}
    $cursorData.mcpServers["helios"] = @{{ url = "{sse_url}" }}
    $cursorJson = $cursorData | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($cursorMcpPath, $cursorJson, [System.Text.Encoding]::UTF8)
    Write-Host "  [OK] Cursor MCP registered in $cursorMcpPath" -ForegroundColor Green
    $cursorRulesPath = Join-Path $cursorDir "rules\\helios.mdc"
    Set-HeliosDirective -FilePath $cursorRulesPath
    Write-Host "  [OK] Cursor directive embedded in $cursorRulesPath" -ForegroundColor Green
}}

# 3. Claude Desktop Configuration (if %APPDATA%\\Claude exists or client is claude-desktop/all)
$claudeDir = Join-Path $env:APPDATA "Claude"
if ((Test-Path $claudeDir) -or "{client_norm}" -eq "claude-desktop") {{
    if (-not (Test-Path $claudeDir)) {{ New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null }}
    $claudeMcpPath = Join-Path $claudeDir "claude_desktop_config.json"
    $claudeData = @{{ mcpServers = @{{}} }}
    if (Test-Path $claudeMcpPath) {{
        try {{
            $clExisting = Get-Content -Path $claudeMcpPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($clExisting -and $clExisting.ContainsKey("mcpServers")) {{ $claudeData = $clExisting }}
        }} catch {{}}
    }}
    if (-not $claudeData.ContainsKey("mcpServers") -or $null -eq $claudeData.mcpServers) {{ $claudeData.mcpServers = @{{}} }}
    $claudeData.mcpServers["helios"] = @{{ command = "npx"; args = @("-y", "mcp-remote", "{sse_url}") }}
    $claudeJson = $claudeData | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($claudeMcpPath, $claudeJson, [System.Text.Encoding]::UTF8)
    Write-Host "  [OK] Claude Desktop MCP registered in $claudeMcpPath" -ForegroundColor Green
}}

$claudeDotDir = Join-Path $env:USERPROFILE ".claude"
if ((Test-Path $claudeDotDir) -or (Test-Path $claudeDir) -or "{client_norm}" -eq "claude-desktop" -or "{client_norm}" -eq "claude-code") {{
    $claudeMdPath = Join-Path $claudeDotDir "CLAUDE.md"
    Set-HeliosDirective -FilePath $claudeMdPath
    Write-Host "  [OK] Claude directive embedded in $claudeMdPath" -ForegroundColor Green
}}

# 4. OpenAI Codex CLI Configuration (~/.codex/config.toml & ~/.codex/AGENTS.md)
$codexDir = Join-Path $env:USERPROFILE ".codex"
if ((Test-Path $codexDir) -or "{client_norm}" -eq "codex") {{
    if (-not (Test-Path $codexDir)) {{ New-Item -ItemType Directory -Path $codexDir -Force | Out-Null }}
    $codexTomlPath = Join-Path $codexDir "config.toml"
    $tomlBlock = "[mcp_servers.helios]`r`nurl = `"{mcp_url}`""
    if (Test-Path $codexTomlPath) {{
        $tContent = [System.IO.File]::ReadAllText($codexTomlPath, [System.Text.Encoding]::UTF8)
        if ($tContent -match '(?ms)^\\[mcp_servers\\.helios\\].*?(?=^\\[|\\z)') {{
            $tContent = [regex]::Replace($tContent, '(?ms)^\\[mcp_servers\\.helios\\].*?(?=^\\[|\\z)', ($tomlBlock + "`r`n"))
        }} else {{
            $tContent = $tContent.TrimEnd() + "`r`n`r`n" + $tomlBlock + "`r`n"
        }}
        [System.IO.File]::WriteAllText($codexTomlPath, $tContent, [System.Text.Encoding]::UTF8)
    }} else {{
        [System.IO.File]::WriteAllText($codexTomlPath, ($tomlBlock + "`r`n"), [System.Text.Encoding]::UTF8)
    }}
    Write-Host "  [OK] OpenAI Codex MCP registered in $codexTomlPath" -ForegroundColor Green
    $codexAgentsPath = Join-Path $codexDir "AGENTS.md"
    Set-HeliosDirective -FilePath $codexAgentsPath
    Write-Host "  [OK] OpenAI Codex directive embedded in $codexAgentsPath" -ForegroundColor Green
}}

# 5. Windsurf Configuration (~/.codeium/windsurf/mcp_config.json & global_rules.md)
$windsurfDir = Join-Path $env:USERPROFILE ".codeium\\windsurf"
if ((Test-Path $windsurfDir) -or "{client_norm}" -eq "windsurf") {{
    if (-not (Test-Path $windsurfDir)) {{ New-Item -ItemType Directory -Path $windsurfDir -Force | Out-Null }}
    $windsurfMcpPath = Join-Path $windsurfDir "mcp_config.json"
    $wsData = @{{ mcpServers = @{{}} }}
    if (Test-Path $windsurfMcpPath) {{
        try {{
            $wsExisting = Get-Content -Path $windsurfMcpPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($wsExisting -and $wsExisting.ContainsKey("mcpServers")) {{ $wsData = $wsExisting }}
        }} catch {{}}
    }}
    if (-not $wsData.ContainsKey("mcpServers") -or $null -eq $wsData.mcpServers) {{ $wsData.mcpServers = @{{}} }}
    $wsData.mcpServers["helios"] = @{{ serverUrl = "{mcp_url}" }}
    $wsJson = $wsData | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($windsurfMcpPath, $wsJson, [System.Text.Encoding]::UTF8)
    Write-Host "  [OK] Windsurf MCP registered in $windsurfMcpPath" -ForegroundColor Green
    $wsRulesPath = Join-Path $windsurfDir "memories\\global_rules.md"
    Set-HeliosDirective -FilePath $wsRulesPath
    Write-Host "  [OK] Windsurf directive embedded in $wsRulesPath" -ForegroundColor Green
}}

# 6. VS Code / GitHub Copilot (%APPDATA%\\Code\\User\\mcp.json & ~/.github/copilot-instructions.md)
$vscodeDir = Join-Path $env:APPDATA "Code\\User"
if ((Test-Path $vscodeDir) -or "{client_norm}" -eq "vscode") {{
    if (-not (Test-Path $vscodeDir)) {{ New-Item -ItemType Directory -Path $vscodeDir -Force | Out-Null }}
    $vscodeMcpPath = Join-Path $vscodeDir "mcp.json"
    $vscData = @{{ servers = @{{}} }}
    if (Test-Path $vscodeMcpPath) {{
        try {{
            $vscExisting = Get-Content -Path $vscodeMcpPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($vscExisting -and $vscExisting.ContainsKey("servers")) {{ $vscData = $vscExisting }}
        }} catch {{}}
    }}
    if (-not $vscData.ContainsKey("servers") -or $null -eq $vscData.servers) {{ $vscData.servers = @{{}} }}
    $vscData.servers["helios"] = @{{ type = "http"; url = "{mcp_url}" }}
    $vscJson = $vscData | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($vscodeMcpPath, $vscJson, [System.Text.Encoding]::UTF8)
    Write-Host "  [OK] VS Code MCP registered in $vscodeMcpPath" -ForegroundColor Green
    $copilotRulesPath = Join-Path $env:USERPROFILE ".github\\copilot-instructions.md"
    Set-HeliosDirective -FilePath $copilotRulesPath
    Write-Host "  [OK] Copilot directive embedded in $copilotRulesPath" -ForegroundColor Green
}}

# 7. OpenCode Configuration (~/.config/opencode/opencode.json & AGENTS.md)
$opencodeDir = Join-Path $env:USERPROFILE ".config\\opencode"
if ((Test-Path $opencodeDir) -or "{client_norm}" -eq "opencode") {{
    if (-not (Test-Path $opencodeDir)) {{ New-Item -ItemType Directory -Path $opencodeDir -Force | Out-Null }}
    $opencodeMcpPath = Join-Path $opencodeDir "opencode.json"
    $ocData = @{{ '$schema' = "https://opencode.ai/config.json"; mcp = @{{}} }}
    if (Test-Path $opencodeMcpPath) {{
        try {{
            $ocExisting = Get-Content -Path $opencodeMcpPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($ocExisting) {{ $ocData = $ocExisting }}
        }} catch {{}}
    }}
    if (-not $ocData.ContainsKey("mcp") -or $null -eq $ocData.mcp) {{ $ocData["mcp"] = @{{}} }}
    $ocData.mcp["helios"] = @{{ type = "remote"; url = "{mcp_url}"; enabled = $true }}
    $ocJson = $ocData | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($opencodeMcpPath, $ocJson, [System.Text.Encoding]::UTF8)
    Write-Host "  [OK] OpenCode MCP registered in $opencodeMcpPath" -ForegroundColor Green
    $ocAgentsPath = Join-Path $opencodeDir "AGENTS.md"
    Set-HeliosDirective -FilePath $ocAgentsPath
    Write-Host "  [OK] OpenCode directive embedded in $ocAgentsPath" -ForegroundColor Green
}}

# 8. Global Directive (GEMINI.md with CRLF and symlink handling)
$geminiPath = Join-Path $configDir "GEMINI.md"
Set-HeliosDirective -FilePath $geminiPath
Write-Host "  [OK] Global directive embedded in $geminiPath" -ForegroundColor Green

# 9. /remember Skill (~/.gemini/skills/remember/SKILL.md)
$skillDir = Join-Path $env:USERPROFILE ".gemini\\skills\\remember"
if (-not (Test-Path $skillDir)) {{ New-Item -ItemType Directory -Path $skillDir -Force | Out-Null }}
$skillPath = Join-Path $skillDir "SKILL.md"
$skillText = @'
{skill}
'@
[System.IO.File]::WriteAllText($skillPath, $skillText, [System.Text.Encoding]::UTF8)
Write-Host "  [OK] /remember skill installed in $skillPath" -ForegroundColor Green

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host "Helios Client Environment Configured Successfully!" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Next actions for AI agent / developer:"
Write-Host "  1. Restart active IDE window or agent session to discover 'helios'."
Write-Host "  2. Call recall_memories(scope='<repo>') to verify memory connection."
Write-Host "  3. Call manage_git_webhooks(action='list') to audit push drift tracking."
"""


def generate_setup_bash(
    base_url: str,
    query_token: str | None = None,
    instance_role: str = "workstation",
    client: str = "all",
) -> str:
    """
    Generate an automated Linux/macOS bash onboarding script.
    Usage: curl -fsSL https://<host>/setup.sh | bash
    Handles multi-client auto-detection, POSIX symlinks, and idempotent marker replacement.
    """
    clean_base = base_url.rstrip("/")
    token_suffix = ""
    if query_token and query_token.strip():
        token_suffix = f"?token={urllib.parse.quote(query_token.strip(), safe='')}"
    mcp_url = f"{clean_base}/mcp{token_suffix}"
    sse_url = f"{clean_base}/sse{token_suffix}"
    active_limit = get_word_limit()
    directive = generate_global_directive(instance_role, word_limit=active_limit).strip()
    skill = generate_remember_skill(word_limit=active_limit).strip()
    guard_script = generate_guard_hook_script().strip()
    role_norm = instance_role.strip().lower()
    client_norm = client.strip().lower()

    return f"""#!/usr/bin/env bash
set -euo pipefail

echo "Configuring Helios client environment for {clean_base} (role: {role_norm})..."

DIRECTIVE_CONTENT="$(cat <<'HELIOS_DIRECTIVE_EOF'
{directive}
HELIOS_DIRECTIVE_EOF
)"

inject_directive() {{
    local target_path="$1"
    mkdir -p "$(dirname "$target_path")"
    TARGET_PATH="$target_path" DIRECTIVE="$DIRECTIVE_CONTENT" python3 - <<'PYEOF'
import os, re
path = os.environ["TARGET_PATH"]
directive = os.environ["DIRECTIVE"]
if os.path.exists(path):
    real_path = os.path.realpath(path)
    with open(real_path, 'r', encoding='utf-8') as f:
        content = f.read()
    if re.search(r'<!-- HELIOS:START(?:\\s+[^>]+)? -->.*?<!-- HELIOS:END -->', content, flags=re.DOTALL):
        new_content = re.sub(
            r'<!-- HELIOS:START(?:\\s+[^>]+)? -->.*?<!-- HELIOS:END -->',
            lambda _: directive,
            content,
            flags=re.DOTALL,
        )
    else:
        new_content = directive + '\\n\\n' + content
    with open(real_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
else:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(directive)
PYEOF
}}

# 1. Antigravity MCP Configuration (~/.gemini/config/mcp_config.json)
CONFIG_DIR="$HOME/.gemini/config"
mkdir -p "$CONFIG_DIR"
MCP_CONFIG="$CONFIG_DIR/mcp_config.json"

MCP_CONFIG="$MCP_CONFIG" MCP_URL="{mcp_url}" python3 - <<'PYEOF'
import json, os
path = os.environ["MCP_CONFIG"]
mcp_url = os.environ["MCP_URL"]
data = {{'mcpServers': {{}}}}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        pass
if 'mcpServers' not in data or not isinstance(data['mcpServers'], dict):
    data['mcpServers'] = {{}}
data['mcpServers']['helios'] = {{'url': mcp_url}}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
PYEOF
echo "  [OK] Antigravity MCP registered in $MCP_CONFIG"

# 2. Cursor MCP Configuration (if ~/.cursor exists or client is cursor/all)
CURSOR_DIR="$HOME/.cursor"
if [ -d "$CURSOR_DIR" ] || [ "{client_norm}" = "cursor" ] || [ "{client_norm}" = "all" ]; then
    mkdir -p "$CURSOR_DIR"
    CURSOR_MCP="$CURSOR_DIR/mcp.json"
    CURSOR_MCP="$CURSOR_MCP" SSE_URL="{sse_url}" python3 - <<'PYEOF'
import json, os
path = os.environ["CURSOR_MCP"]
sse_url = os.environ["SSE_URL"]
data = {{'mcpServers': {{}}}}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        pass
if 'mcpServers' not in data or not isinstance(data['mcpServers'], dict):
    data['mcpServers'] = {{}}
data['mcpServers']['helios'] = {{'url': sse_url}}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
PYEOF
    echo "  [OK] Cursor MCP registered in $CURSOR_MCP"
    inject_directive "$CURSOR_DIR/rules/helios.mdc"
    echo "  [OK] Cursor directive embedded in $CURSOR_DIR/rules/helios.mdc"
fi

# 3. Claude Desktop Configuration (if directory exists or client is claude-desktop/all)
for CLAUDE_BASE in "$HOME/.config/Claude" "$HOME/Library/Application Support/Claude"; do
    if [ -d "$CLAUDE_BASE" ] || [ "{client_norm}" = "claude-desktop" ]; then
        mkdir -p "$CLAUDE_BASE"
        CLAUDE_MCP="$CLAUDE_BASE/claude_desktop_config.json"
        CLAUDE_MCP="$CLAUDE_MCP" SSE_URL="{sse_url}" python3 - <<'PYEOF'
import json, os
path = os.environ["CLAUDE_MCP"]
sse_url = os.environ["SSE_URL"]
data = {{'mcpServers': {{}}}}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        pass
if 'mcpServers' not in data or not isinstance(data['mcpServers'], dict):
    data['mcpServers'] = {{}}
data['mcpServers']['helios'] = {{'command': 'npx', 'args': ['-y', 'mcp-remote', sse_url]}}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
PYEOF
        echo "  [OK] Claude Desktop MCP registered in $CLAUDE_MCP"
        break
    fi
done

# 4. Claude Code CLI (if claude CLI binary exists in PATH or client matches)
if command -v claude >/dev/null 2>&1; then
    claude mcp add --transport sse helios "{sse_url}" >/dev/null 2>&1 || true
    echo "  [OK] Claude Code CLI MCP registered"
fi
if [ -d "$HOME/.claude" ] || command -v claude >/dev/null 2>&1 || [ "{client_norm}" = "claude-code" ] || [ "{client_norm}" = "claude-desktop" ]; then
    inject_directive "$HOME/.claude/CLAUDE.md"
    echo "  [OK] Claude directive embedded in $HOME/.claude/CLAUDE.md"
fi

# 5. OpenAI Codex CLI (if ~/.codex or codex binary exists or client is codex)
CODEX_DIR="$HOME/.codex"
if [ -d "$CODEX_DIR" ] || command -v codex >/dev/null 2>&1 || [ "{client_norm}" = "codex" ]; then
    mkdir -p "$CODEX_DIR"
    CODEX_TOML="$CODEX_DIR/config.toml"
    CODEX_TOML="$CODEX_TOML" MCP_URL="{mcp_url}" python3 - <<'PYEOF'
import os, re
path = os.environ["CODEX_TOML"]
mcp_url = os.environ["MCP_URL"]
block = f"[mcp_servers.helios]\\nurl = \\"{mcp_url}\\"\\n"
if os.path.exists(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if re.search(r'(?ms)^\\[mcp_servers\\.helios\\].*?(?=^\\[|\\Z)', content):
        content = re.sub(r'(?ms)^\\[mcp_servers\\.helios\\].*?(?=^\\[|\\Z)', block, content)
    else:
        content = content.rstrip() + "\\n\\n" + block
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
else:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(block)
PYEOF
    echo "  [OK] OpenAI Codex MCP registered in $CODEX_TOML"
    inject_directive "$CODEX_DIR/AGENTS.md"
    echo "  [OK] OpenAI Codex directive embedded in $CODEX_DIR/AGENTS.md"
fi

# 6. Windsurf Configuration (if ~/.codeium/windsurf exists or client is windsurf)
WINDSURF_DIR="$HOME/.codeium/windsurf"
if [ -d "$WINDSURF_DIR" ] || [ "{client_norm}" = "windsurf" ]; then
    mkdir -p "$WINDSURF_DIR"
    WINDSURF_MCP="$WINDSURF_DIR/mcp_config.json"
    WINDSURF_MCP="$WINDSURF_MCP" MCP_URL="{mcp_url}" python3 - <<'PYEOF'
import json, os
path = os.environ["WINDSURF_MCP"]
mcp_url = os.environ["MCP_URL"]
data = {{'mcpServers': {{}}}}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        pass
if 'mcpServers' not in data or not isinstance(data['mcpServers'], dict):
    data['mcpServers'] = {{}}
data['mcpServers']['helios'] = {{'serverUrl': mcp_url}}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
PYEOF
    echo "  [OK] Windsurf MCP registered in $WINDSURF_MCP"
    inject_directive "$WINDSURF_DIR/memories/global_rules.md"
    echo "  [OK] Windsurf directive embedded in $WINDSURF_DIR/memories/global_rules.md"
fi

# 7. VS Code / GitHub Copilot (if Code/User dir exists or client is vscode)
for VSCODE_BASE in "$HOME/.config/Code/User" "$HOME/Library/Application Support/Code/User"; do
    if [ -d "$VSCODE_BASE" ] || [ "{client_norm}" = "vscode" ]; then
        mkdir -p "$VSCODE_BASE"
        VSCODE_MCP="$VSCODE_BASE/mcp.json"
        VSCODE_MCP="$VSCODE_MCP" MCP_URL="{mcp_url}" python3 - <<'PYEOF'
import json, os
path = os.environ["VSCODE_MCP"]
mcp_url = os.environ["MCP_URL"]
data = {{'servers': {{}}}}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        pass
if 'servers' not in data or not isinstance(data['servers'], dict):
    data['servers'] = {{}}
data['servers']['helios'] = {{'type': 'http', 'url': mcp_url}}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
PYEOF
        echo "  [OK] VS Code MCP registered in $VSCODE_MCP"
        inject_directive "$HOME/.github/copilot-instructions.md"
        echo "  [OK] Copilot directive embedded in $HOME/.github/copilot-instructions.md"
        break
    fi
done

# 8. OpenCode Configuration (if ~/.config/opencode or opencode binary exists or client is opencode)
OPENCODE_DIR="$HOME/.config/opencode"
if [ -d "$OPENCODE_DIR" ] || command -v opencode >/dev/null 2>&1 || [ "{client_norm}" = "opencode" ]; then
    mkdir -p "$OPENCODE_DIR"
    OPENCODE_MCP="$OPENCODE_DIR/opencode.json"
    OPENCODE_MCP="$OPENCODE_MCP" MCP_URL="{mcp_url}" python3 - <<'PYEOF'
import json, os
path = os.environ["OPENCODE_MCP"]
mcp_url = os.environ["MCP_URL"]
data = {{'$schema': 'https://opencode.ai/config.json', 'mcp': {{}}}}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        pass
if 'mcp' not in data or not isinstance(data['mcp'], dict):
    data['mcp'] = {{}}
data['mcp']['helios'] = {{'type': 'remote', 'url': mcp_url, 'enabled': True}}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
PYEOF
    echo "  [OK] OpenCode MCP registered in $OPENCODE_MCP"
    inject_directive "$OPENCODE_DIR/AGENTS.md"
    echo "  [OK] OpenCode directive embedded in $OPENCODE_DIR/AGENTS.md"
fi

# 9. Global Directive (GEMINI.md with symlink resolution)
GEMINI_PATH="$CONFIG_DIR/GEMINI.md"
inject_directive "$GEMINI_PATH"
echo "  [OK] Global directive embedded in $GEMINI_PATH"

# 10. /remember Skill (~/.gemini/skills/remember/SKILL.md)
SKILL_DIR="$HOME/.gemini/skills/remember"
mkdir -p "$SKILL_DIR"
cat <<'HELIOS_SKILL_EOF' > "$SKILL_DIR/SKILL.md"
{skill}
HELIOS_SKILL_EOF
echo "  [OK] /remember skill installed in $SKILL_DIR/SKILL.md"

# 11. Antigravity Cognitive Guard Hook (~/.gemini/config/hooks.json & scripts/helios_guard.py)
SCRIPTS_DIR="$CONFIG_DIR/scripts"
mkdir -p "$SCRIPTS_DIR"
cat <<'HELIOS_GUARD_EOF' > "$SCRIPTS_DIR/helios_guard.py"
{guard_script}
HELIOS_GUARD_EOF
chmod +x "$SCRIPTS_DIR/helios_guard.py"

HOOKS_PATH="$CONFIG_DIR/hooks.json"
HOOKS_PATH="$HOOKS_PATH" python3 - <<'PYEOF'
import json, os
path = os.environ["HOOKS_PATH"]
data = {{}}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        pass
if not isinstance(data, dict):
    data = {{}}
data['helios-write-through-guard'] = {{
    'PreInvocation': [
        {{
            'type': 'command',
            'command': 'python3 ' + os.path.expanduser('~/.gemini/config/scripts/helios_guard.py'),
            'timeout': 5,
        }}
    ]
}}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
PYEOF
echo "  [OK] Helios Write-Through guard hook registered in $HOOKS_PATH"

echo ""
echo "=================================================="
echo "Helios client onboarding complete!"
echo "Action required for AI agents:"
echo "  1. Restart active IDE window or CLI agent session to load 'helios'."
echo "  2. Call recall_memories(scope='<repo>') to verify memory connection."
echo "  3. Call manage_git_webhooks(action='list') to audit push drift tracking."
echo "=================================================="
"""


def generate_uninstall_powershell(base_url: str = "", client: str = "all") -> str:
    """
    Generate an automated Windows PowerShell uninstallation script.
    Usage: irm https://<host>/uninstall.ps1 | iex
    Removes Helios MCP registrations, marker directive blocks, guard hooks, and skills.
    """
    client_norm = (client or "all").strip().lower()

    return f"""# Helios Automated Client Uninstaller for Windows PowerShell
$ErrorActionPreference = 'Continue'
Write-Host "Uninstalling Helios client configuration (client: {client_norm})..." -ForegroundColor Cyan

function Remove-HeliosDirective {{
    param([string]$FilePath)
    if (Test-Path $FilePath) {{
        $resolvedPath = (Resolve-Path $FilePath).Path
        $content = [System.IO.File]::ReadAllText($resolvedPath, [System.Text.Encoding]::UTF8)
        if ($content -match '(?s)<!-- HELIOS:START(?:\\s+[^>]+)? -->.*?<!-- HELIOS:END -->') {{
            $newContent = [regex]::Replace($content, '(?s)<!-- HELIOS:START(?:\\s+[^>]+)? -->.*?<!-- HELIOS:END -->', '')
            $trimmed = $newContent.Trim()
            if ($FilePath -like '*.mdc' -and [string]::IsNullOrWhiteSpace($trimmed)) {{
                Remove-Item -Path $resolvedPath -Force -ErrorAction SilentlyContinue
                Write-Host "  [OK] Removed empty directive rule $resolvedPath" -ForegroundColor Green
            }} else {{
                [System.IO.File]::WriteAllText($resolvedPath, ($trimmed + "`r`n"), [System.Text.Encoding]::UTF8)
                Write-Host "  [OK] Stripped Helios directive from $resolvedPath" -ForegroundColor Green
            }}
        }}
    }}
}}

# 1. Antigravity MCP & Directives
$configDir = Join-Path $env:USERPROFILE ".gemini\\config"
if ("{client_norm}" -eq "antigravity" -or "{client_norm}" -eq "all") {{
    $mcpPath = Join-Path $configDir "mcp_config.json"
    if (Test-Path $mcpPath) {{
        try {{
            $data = Get-Content -Path $mcpPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($data -and $data.ContainsKey("mcpServers") -and $data.mcpServers.ContainsKey("helios")) {{
                $data.mcpServers.Remove("helios")
                $json = $data | ConvertTo-Json -Depth 10
                [System.IO.File]::WriteAllText($mcpPath, $json, [System.Text.Encoding]::UTF8)
                Write-Host "  [OK] Removed helios from $mcpPath" -ForegroundColor Green
            }}
        }} catch {{}}
    }}
    Remove-HeliosDirective -FilePath (Join-Path $configDir "GEMINI.md")

    # Guard Hook
    $hooksPath = Join-Path $configDir "hooks.json"
    if (Test-Path $hooksPath) {{
        try {{
            $hData = Get-Content -Path $hooksPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($hData -and $hData.ContainsKey("helios-write-through-guard")) {{
                $hData.Remove("helios-write-through-guard")
                $hJson = $hData | ConvertTo-Json -Depth 10
                [System.IO.File]::WriteAllText($hooksPath, $hJson, [System.Text.Encoding]::UTF8)
                Write-Host "  [OK] Removed helios guard hook from $hooksPath" -ForegroundColor Green
            }}
        }} catch {{}}
    }}
    $guardScript = Join-Path $configDir "scripts\\helios_guard.py"
    if (Test-Path $guardScript) {{
        Remove-Item -Path $guardScript -Force -ErrorAction SilentlyContinue
        Write-Host "  [OK] Deleted $guardScript" -ForegroundColor Green
    }}

    # /remember skill
    $skillDir = Join-Path $env:USERPROFILE ".gemini\\skills\\remember"
    if (Test-Path $skillDir) {{
        Remove-Item -Path $skillDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  [OK] Deleted $skillDir" -ForegroundColor Green
    }}
}}

# 2. Cursor
if ("{client_norm}" -eq "cursor" -or "{client_norm}" -eq "all") {{
    $cursorDir = Join-Path $env:USERPROFILE ".cursor"
    $cMcp = Join-Path $cursorDir "mcp.json"
    if (Test-Path $cMcp) {{
        try {{
            $cData = Get-Content -Path $cMcp -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($cData -and $cData.ContainsKey("mcpServers") -and $cData.mcpServers.ContainsKey("helios")) {{
                $cData.mcpServers.Remove("helios")
                $cJson = $cData | ConvertTo-Json -Depth 10
                [System.IO.File]::WriteAllText($cMcp, $cJson, [System.Text.Encoding]::UTF8)
                Write-Host "  [OK] Removed helios from $cMcp" -ForegroundColor Green
            }}
        }} catch {{}}
    }}
    Remove-HeliosDirective -FilePath (Join-Path $cursorDir "rules\\helios.mdc")
}}

# 3. Claude Desktop & Claude Code
if ("{client_norm}" -eq "claude-desktop" -or "{client_norm}" -eq "claude-code" -or "{client_norm}" -eq "all") {{
    $claudeDir = Join-Path $env:APPDATA "Claude"
    $clMcp = Join-Path $claudeDir "claude_desktop_config.json"
    if (Test-Path $clMcp) {{
        try {{
            $clData = Get-Content -Path $clMcp -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($clData -and $clData.ContainsKey("mcpServers") -and $clData.mcpServers.ContainsKey("helios")) {{
                $clData.mcpServers.Remove("helios")
                $clJson = $clData | ConvertTo-Json -Depth 10
                [System.IO.File]::WriteAllText($clMcp, $clJson, [System.Text.Encoding]::UTF8)
                Write-Host "  [OK] Removed helios from $clMcp" -ForegroundColor Green
            }}
        }} catch {{}}
    }}
    $claudeDot = Join-Path $env:USERPROFILE ".claude"
    Remove-HeliosDirective -FilePath (Join-Path $claudeDot "CLAUDE.md")
    if (Get-Command claude -ErrorAction SilentlyContinue) {{
        try {{ claude mcp remove helios 2>$null }} catch {{}}
    }}
}}

# 4. OpenAI Codex
if ("{client_norm}" -eq "codex" -or "{client_norm}" -eq "all") {{
    $codexDir = Join-Path $env:USERPROFILE ".codex"
    $cToml = Join-Path $codexDir "config.toml"
    if (Test-Path $cToml) {{
        try {{
            $tContent = [System.IO.File]::ReadAllText($cToml, [System.Text.Encoding]::UTF8)
            if ($tContent -match '(?ms)^\\[mcp_servers\\.helios\\].*?(?=^\\[|\\z)') {{
                $tContent = [regex]::Replace($tContent, '(?ms)^\\[mcp_servers\\.helios\\].*?(?=^\\[|\\z)', '')
                [System.IO.File]::WriteAllText($cToml, $tContent.TrimEnd() + "`r`n", [System.Text.Encoding]::UTF8)
                Write-Host "  [OK] Removed helios from $cToml" -ForegroundColor Green
            }}
        }} catch {{}}
    }}
    Remove-HeliosDirective -FilePath (Join-Path $codexDir "AGENTS.md")
}}

# 5. Windsurf
if ("{client_norm}" -eq "windsurf" -or "{client_norm}" -eq "all") {{
    $wsDir = Join-Path $env:USERPROFILE ".codeium\\windsurf"
    $wsMcp = Join-Path $wsDir "mcp_config.json"
    if (Test-Path $wsMcp) {{
        try {{
            $wsData = Get-Content -Path $wsMcp -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($wsData -and $wsData.ContainsKey("mcpServers") -and $wsData.mcpServers.ContainsKey("helios")) {{
                $wsData.mcpServers.Remove("helios")
                $wsJson = $wsData | ConvertTo-Json -Depth 10
                [System.IO.File]::WriteAllText($wsMcp, $wsJson, [System.Text.Encoding]::UTF8)
                Write-Host "  [OK] Removed helios from $wsMcp" -ForegroundColor Green
            }}
        }} catch {{}}
    }}
    Remove-HeliosDirective -FilePath (Join-Path $wsDir "memories\\global_rules.md")
}}

# 6. VS Code
if ("{client_norm}" -eq "vscode" -or "{client_norm}" -eq "all") {{
    $vscDir = Join-Path $env:APPDATA "Code\\User"
    $vscMcp = Join-Path $vscDir "mcp.json"
    if (Test-Path $vscMcp) {{
        try {{
            $vscData = Get-Content -Path $vscMcp -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($vscData -and $vscData.ContainsKey("servers") -and $vscData.servers.ContainsKey("helios")) {{
                $vscData.servers.Remove("helios")
                $vscJson = $vscData | ConvertTo-Json -Depth 10
                [System.IO.File]::WriteAllText($vscMcp, $vscJson, [System.Text.Encoding]::UTF8)
                Write-Host "  [OK] Removed helios from $vscMcp" -ForegroundColor Green
            }}
        }} catch {{}}
    }}
    Remove-HeliosDirective -FilePath (Join-Path $env:USERPROFILE ".github\\copilot-instructions.md")
}}

# 7. OpenCode
if ("{client_norm}" -eq "opencode" -or "{client_norm}" -eq "all") {{
    $ocDir = Join-Path $env:USERPROFILE ".config\\opencode"
    $ocMcp = Join-Path $ocDir "opencode.json"
    if (Test-Path $ocMcp) {{
        try {{
            $ocData = Get-Content -Path $ocMcp -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
            if ($ocData -and $ocData.ContainsKey("mcp") -and $ocData.mcp.ContainsKey("helios")) {{
                $ocData.mcp.Remove("helios")
                $ocJson = $ocData | ConvertTo-Json -Depth 10
                [System.IO.File]::WriteAllText($ocMcp, $ocJson, [System.Text.Encoding]::UTF8)
                Write-Host "  [OK] Removed helios from $ocMcp" -ForegroundColor Green
            }}
        }} catch {{}}
    }}
    Remove-HeliosDirective -FilePath (Join-Path $ocDir "AGENTS.md")
}}

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host "Helios uninstallation complete!" -ForegroundColor Cyan
Write-Host "Restart active IDE windows or CLI agent sessions to flush memory caches." -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
"""


def generate_uninstall_bash(base_url: str = "", client: str = "all") -> str:
    """
    Generate an automated Linux/macOS bash uninstallation script.
    Usage: curl -fsSL https://<host>/uninstall.sh | bash
    Removes Helios MCP registrations, marker directive blocks, guard hooks, and skills.
    """
    client_norm = (client or "all").strip().lower()

    return f"""#!/usr/bin/env bash
set -euo pipefail

echo "Uninstalling Helios client configuration (client: {client_norm})..."

strip_directive() {{
    local target_path="$1"
    if [ -f "$target_path" ]; then
        TARGET_PATH="$target_path" python3 - <<'PYEOF'
import os, re
target_path = os.environ["TARGET_PATH"]
real_path = os.path.realpath(target_path)
with open(real_path, 'r', encoding='utf-8') as f:
    content = f.read()
if re.search(r'<!-- HELIOS:START(?:\\s+[^>]+)? -->.*?<!-- HELIOS:END -->', content, flags=re.DOTALL):
    new_content = re.sub(r'<!-- HELIOS:START(?:\\s+[^>]+)? -->.*?<!-- HELIOS:END -->', '', content, flags=re.DOTALL).strip()
    if target_path.endswith('.mdc') and not new_content:
        os.remove(real_path)
        print("  [OK] Removed empty directive rule " + target_path)
    else:
        with open(real_path, 'w', encoding='utf-8') as f:
            f.write(new_content + '\\n' if new_content else '')
        print("  [OK] Stripped Helios directive from " + target_path)
PYEOF
    fi
}}

# 1. Antigravity MCP & Directives
if [ "{client_norm}" = "antigravity" ] || [ "{client_norm}" = "all" ]; then
    CONFIG_DIR="$HOME/.gemini/config"
    MCP_CONFIG="$CONFIG_DIR/mcp_config.json"
    if [ -f "$MCP_CONFIG" ]; then
        MCP_CONFIG="$MCP_CONFIG" python3 - <<'PYEOF'
import json, os
mcp_path = os.environ["MCP_CONFIG"]
try:
    with open(mcp_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'mcpServers' in data and 'helios' in data['mcpServers']:
        del data['mcpServers']['helios']
        with open(mcp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print("  [OK] Removed helios from " + mcp_path)
except Exception:
    pass
PYEOF
    fi
    strip_directive "$CONFIG_DIR/GEMINI.md"

    # Guard Hook
    HOOKS_PATH="$CONFIG_DIR/hooks.json"
    if [ -f "$HOOKS_PATH" ]; then
        HOOKS_PATH="$HOOKS_PATH" python3 - <<'PYEOF'
import json, os
hooks_path = os.environ["HOOKS_PATH"]
try:
    with open(hooks_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'helios-write-through-guard' in data:
        del data['helios-write-through-guard']
        with open(hooks_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print("  [OK] Removed helios guard hook from " + hooks_path)
except Exception:
    pass
PYEOF
    fi
    rm -f "$CONFIG_DIR/scripts/helios_guard.py"
    rm -rf "$HOME/.gemini/skills/remember" "$HOME/.gemini/config/skills/remember"
    echo "  [OK] Removed /remember skill and guard script"
fi

# 2. Cursor
if [ "{client_norm}" = "cursor" ] || [ "{client_norm}" = "all" ]; then
    CURSOR_MCP="$HOME/.cursor/mcp.json"
    if [ -f "$CURSOR_MCP" ]; then
        CURSOR_MCP="$CURSOR_MCP" python3 - <<'PYEOF'
import json, os
cursor_path = os.environ["CURSOR_MCP"]
try:
    with open(cursor_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'mcpServers' in data and 'helios' in data['mcpServers']:
        del data['mcpServers']['helios']
        with open(cursor_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print("  [OK] Removed helios from " + cursor_path)
except Exception:
    pass
PYEOF
    fi
    strip_directive "$HOME/.cursor/rules/helios.mdc"
fi

# 3. Claude Desktop & Claude Code
if [ "{client_norm}" = "claude-desktop" ] || [ "{client_norm}" = "claude-code" ] || [ "{client_norm}" = "all" ]; then
    for CLAUDE_BASE in "$HOME/.config/Claude" "$HOME/Library/Application Support/Claude"; do
        CLAUDE_MCP="$CLAUDE_BASE/claude_desktop_config.json"
        if [ -f "$CLAUDE_MCP" ]; then
            CLAUDE_MCP="$CLAUDE_MCP" python3 - <<'PYEOF'
import json, os
claude_path = os.environ["CLAUDE_MCP"]
try:
    with open(claude_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'mcpServers' in data and 'helios' in data['mcpServers']:
        del data['mcpServers']['helios']
        with open(claude_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print("  [OK] Removed helios from " + claude_path)
except Exception:
    pass
PYEOF
        fi
    done
    strip_directive "$HOME/.claude/CLAUDE.md"
    if command -v claude >/dev/null 2>&1; then
        claude mcp remove helios >/dev/null 2>&1 || true
        echo "  [OK] Claude Code CLI MCP removed"
    fi
fi

# 4. OpenAI Codex
if [ "{client_norm}" = "codex" ] || [ "{client_norm}" = "all" ]; then
    CODEX_TOML="$HOME/.codex/config.toml"
    if [ -f "$CODEX_TOML" ]; then
        CODEX_TOML="$CODEX_TOML" python3 - <<'PYEOF'
import os, re
codex_path = os.environ["CODEX_TOML"]
try:
    with open(codex_path, 'r', encoding='utf-8') as f:
        content = f.read()
    if re.search(r'(?ms)^\\[mcp_servers\\.helios\\].*?(?=^\\[|\\Z)', content):
        new_content = re.sub(r'(?ms)^\\[mcp_servers\\.helios\\].*?(?=^\\[|\\Z)', '', content).strip()
        with open(codex_path, 'w', encoding='utf-8') as f:
            f.write(new_content + '\\n' if new_content else '')
        print("  [OK] Removed helios from " + codex_path)
except Exception:
    pass
PYEOF
    fi
    strip_directive "$HOME/.codex/AGENTS.md"
    if command -v codex >/dev/null 2>&1; then
        codex mcp remove helios >/dev/null 2>&1 || true
    fi
fi

# 5. Windsurf
if [ "{client_norm}" = "windsurf" ] || [ "{client_norm}" = "all" ]; then
    WINDSURF_MCP="$HOME/.codeium/windsurf/mcp_config.json"
    if [ -f "$WINDSURF_MCP" ]; then
        WINDSURF_MCP="$WINDSURF_MCP" python3 - <<'PYEOF'
import json, os
windsurf_path = os.environ["WINDSURF_MCP"]
try:
    with open(windsurf_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'mcpServers' in data and 'helios' in data['mcpServers']:
        del data['mcpServers']['helios']
        with open(windsurf_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print("  [OK] Removed helios from " + windsurf_path)
except Exception:
    pass
PYEOF
    fi
    strip_directive "$HOME/.codeium/windsurf/memories/global_rules.md"
fi

# 6. VS Code
if [ "{client_norm}" = "vscode" ] || [ "{client_norm}" = "all" ]; then
    for VSCODE_BASE in "$HOME/.config/Code/User" "$HOME/Library/Application Support/Code/User"; do
        VSCODE_MCP="$VSCODE_BASE/mcp.json"
        if [ -f "$VSCODE_MCP" ]; then
            VSCODE_MCP="$VSCODE_MCP" python3 - <<'PYEOF'
import json, os
vscode_path = os.environ["VSCODE_MCP"]
try:
    with open(vscode_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'servers' in data and 'helios' in data['servers']:
        del data['servers']['helios']
        with open(vscode_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print("  [OK] Removed helios from " + vscode_path)
except Exception:
    pass
PYEOF
        fi
    done
    strip_directive "$HOME/.github/copilot-instructions.md"
fi

# 7. OpenCode
if [ "{client_norm}" = "opencode" ] || [ "{client_norm}" = "all" ]; then
    OPENCODE_MCP="$HOME/.config/opencode/opencode.json"
    if [ -f "$OPENCODE_MCP" ]; then
        OPENCODE_MCP="$OPENCODE_MCP" python3 - <<'PYEOF'
import json, os
opencode_path = os.environ["OPENCODE_MCP"]
try:
    with open(opencode_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'mcp' in data and 'helios' in data['mcp']:
        del data['mcp']['helios']
        with open(opencode_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print("  [OK] Removed helios from " + opencode_path)
except Exception:
    pass
PYEOF
    fi
    strip_directive "$HOME/.config/opencode/AGENTS.md"
fi

echo ""
echo "=================================================="
echo "Helios uninstallation complete!"
echo "Restart active IDE windows or CLI agent sessions to flush memory caches."
echo "=================================================="
"""
