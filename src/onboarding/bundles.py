"""Markdown setup runbooks and client configuration bundle generators."""

import json
import urllib.parse

from src.config import get_api_key, get_word_limit
from src.onboarding.client_config import (
    SUPPORTED_CLIENTS,
    get_directive_path,
    get_mcp_config_path,
    get_mcp_config_snippet,
    normalize_os_platform,
    resolve_server_base_url,
    validate_onboarding_params,
)
from src.onboarding.templates import (
    generate_global_directive,
    generate_remember_skill,
)


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
    instance_role, client = validate_onboarding_params(instance_role, client)
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


__all__ = [
    "generate_client_bundle",
    "generate_setup_markdown",
]
