"""
Helios AI-Driven Client Onboarding Module.

Generates structured installation instructions, non-destructive MCP JSON configs,
global agent directives (GEMINI.md / CLAUDE.md / .cursor/rules) with idempotent <!-- HELIOS:START --> markers,
and the /remember skill for Antigravity, Cursor, Claude Desktop, and Claude Code across Windows, Linux, and macOS.
"""

import json
import re
import sys
import urllib.parse
from typing import Any

from src.config import get_api_key, get_public_url, get_word_limit


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
    return "~/.mcp/config.json"


def get_mcp_config_snippet(
    client: str,
    base_url: str,
    token: str | None = None,
) -> dict[str, Any] | str:
    """Generate the exact JSON configuration block or CLI command for the client."""
    c = client.strip().lower()
    clean_base = base_url.rstrip("/")
    token_suffix = ""
    if token:
        clean_tok = token.strip()
        if clean_tok == "<YOUR_HELIOS_API_KEY>":
            token_suffix = f"?token={clean_tok}"
        else:
            token_suffix = f"?token={urllib.parse.quote(clean_tok, safe='')}"

    sse_url = f"{clean_base}/sse{token_suffix}"

    if c == "antigravity":
        mcp_url = f"{clean_base}/mcp{token_suffix}"
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
) -> str:
    """
    Generate the global agent directive template (GEMINI.md / CLAUDE.md / .cursor/rules/helios.mdc)
    wrapped in explicit <!-- HELIOS:START --> and <!-- HELIOS:END --> markers.
    """
    role = instance_role.strip().lower()
    limit = word_limit if word_limit is not None else get_word_limit()

    if role == "server-cli":
        body = (
            "# Global Agent Directives — Helios Memory Protocol (Server CLI)\n\n"
            "You are connected to **Helios**, a centralized token-budgeted memory engine.\n\n"
            "## Mandatory Operating Rules:\n"
            "1. **Pre-Flight Memory Check**: Always call `recall_memories(scope=\"<repo_or_dir>\")` at the beginning of any session or task.\n"
            "   - If modifying infrastructure, docker compose stacks, or system services, also check `recall_memories(scope=\"homelab\")`.\n"
            "2. **Configuration Drift Check**: If investigating past parameter values or regressions, call `recall_history(scope=\"<repo>\")`.\n"
            "3. **Stale Memory Protocol**: When a memory is marked `[STALE]`, inspect its referenced `anchor_files`:\n"
            "   - If verified still accurate: call `revalidate_memories(memory_ids=[<id>])`.\n"
            "   - If changed: call `save_memory(scope=..., category='fact', content=..., subject='...')` to supersede it.\n"
            f"4. **AUDN Write Gate & Token Diet**:\n"
            f"   - Facts MUST be atomic and **<= {limit} words**. Omit filler words.\n"
            "   - Category must be one of: `'rule'` (guardrails), `'fact'` (architecture/ports), `'preference'` (style), `'episodic'` (temporary 14d notes).\n"
            "5. **Terminal Token Diet (Headless Host)**:\n"
            "   - Never run unbounded logs. Always use `docker logs --tail=50`, `journalctl -n 40 --no-pager`, and `git status -s`.\n"
            "   - Generate targeted unified diffs or minimal block replacements rather than entire redundant files.\n"
            "6. **Session Memory Maintenance**: Before ending any session, run `/remember` or call `save_memory()` to capture architectural decisions, new tools/endpoints, changed ports/paths, or non-obvious bug fixes."
        )
    else:
        # Workstation / IDE environment (default)
        body = (
            "# Global Agent Directives — Helios Memory Protocol\n\n"
            "You are connected to **Helios**, a centralized token-budgeted memory engine.\n\n"
            "## Mandatory Operating Rules:\n"
            "1. **Pre-Flight Memory Check**: Always call `recall_memories(scope=\"<current_repo_or_project>\")` at the start of any conversation or task.\n"
            "2. **Stale Memory Protocol**: When a memory is flagged `[STALE]`, inspect the referenced `anchor_files` before relying on it:\n"
            "   - If still accurate: call `revalidate_memories(memory_ids=[<id>])`.\n"
            "   - If updated: call `save_memory(scope=..., category='fact', content=..., subject='...')`.\n"
            "3. **Architectural Updates & Session Maintenance**: When adding dependencies, changing ports, establishing conventions, or fixing non-obvious bugs, persist them immediately or at session close with `save_memory()`.\n"
            f"4. **AUDN Write Gate**: Keep facts atomic and **<= {limit} words**. Omit conversational filler. Never store API secrets or bulky code dumps.\n"
            "5. **Session Wrap-Up**: Call the `/remember` skill or `save_memory()` before clearing context to record key findings."
        )

    return f"<!-- HELIOS:START -->\n{body}\n<!-- HELIOS:END -->"


def generate_remember_skill(word_limit: int | None = None) -> str:
    """Generate the ~/.gemini/skills/remember/SKILL.md skill definition."""
    limit = word_limit if word_limit is not None else get_word_limit()
    return (
        "---\n"
        "name: remember\n"
        "description: Distill durable architecture rules, changed ports, and bug learnings from the current session into Helios before clearing context.\n"
        "---\n\n"
        "# Helios Remember Skill\n\n"
        "Use this skill at the end of a session or after significant architectural changes.\n\n"
        "## Steps to Execute:\n"
        "1. **Analyze Session Learnings**: Identify new ports, stack configs, bug fixes, or coding guardrails established in this conversation.\n"
        "2. **Check Existing Slots**: Call `recall_memories(scope=\"<current_scope>\")` to find existing subject slots.\n"
        "3. **Persist Updates**:\n"
        "   - To update a fact: `save_memory(scope=..., category='fact', content=..., subject='<slot_key>')` (automatically supersedes older records sharing slot).\n"
        "   - To set a coding guardrail: `save_memory(scope=..., category='rule', content=...)`.\n"
        "   - To revalidate an inspected stale fact: `revalidate_memories(memory_ids=[...])`.\n"
        "   - To archive an obsolete fact: `deprecate_memory(memory_id=..., reason=...)`.\n"
        f"4. **Word Limit**: Ensure all facts are atomic and `<={limit} words`.\n"
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
            "Follow these steps to cleanly remove Helios from your local environment:",
            "",
            "### 1. Remove MCP Server Entry",
        ]
        target_clients = (
            ["antigravity", "cursor", "claude-desktop", "claude-code"]
            if client == "all"
            else [client]
        )
        for c in target_clients:
            path = get_mcp_config_path(c, plat)
            if c == "claude-code":
                lines.append(f"- **Claude Code**: Run CLI command `claude mcp remove helios`")
            else:
                lines.append(f"- **{c.capitalize()}**: Open `{path}` and remove the `\"helios\"` key under `\"mcpServers\"`.")

        lines.extend([
            "",
            "### 2. Remove Global Directive Block",
            "In your global directive file (`GEMINI.md`, `CLAUDE.md`, or `.cursor/rules/helios.mdc`),",
            "delete the section bounded by the Helios markers (including the markers):",
            "```markdown",
            "<!-- HELIOS:START -->",
            "... (delete everything between and including these markers) ...",
            "<!-- HELIOS:END -->",
            "```",
            "",
            "### 3. Remove `/remember` Skill",
            "Delete the skill file:",
            "- Path: `~/.gemini/skills/remember/SKILL.md` (or the folder `~/.gemini/skills/remember`)",
            "",
            "Helios has been uninstalled from this client environment.",
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
        "> 2. In `GEMINI.md` / `CLAUDE.md`, if `<!-- HELIOS:START -->...<!-- HELIOS:END -->` already exists,",
        ">    replace only the content between those markers. Do NOT clobber other custom user instructions.",
        "",
        "---",
        "## 1. MCP Configuration",
        "",
    ]

    clients_to_show = (
        ["antigravity", "cursor", "claude-desktop", "claude-code"]
        if client == "all"
        else [client]
    )

    for c in clients_to_show:
        path = get_mcp_config_path(c, os_platform)
        snippet = get_mcp_config_snippet(c, resolved_base, token_placeholder)
        lines.append(f"### {c.capitalize()}")
        lines.append(f"**Path**: `{path}`")
        if isinstance(snippet, dict):
            lines.append("```json")
            lines.append(json.dumps(snippet, indent=2))
            lines.append("```")
        else:
            lines.append("```bash")
            lines.append(snippet)
            lines.append("```")
        lines.append("")

    lines.extend([
        "---",
        "## 2. Global Agent Directive (`GEMINI.md` / `CLAUDE.md` / `.cursor/rules/helios.mdc`)",
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
        "2. Safely read and merge the `mcpServers.helios` block into the appropriate MCP config file without clobbering existing servers.\n"
        "3. Configure the Global Agent Directive (`GEMINI.md`, `CLAUDE.md`, or `.cursor/rules/helios.mdc`). "
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
        "- **Path (Linux/macOS)**: `~/.gemini/config/mcp_config.json`\n"
        "- **Path (Windows)**: `%USERPROFILE%\\.gemini\\config\\mcp_config.json`\n"
        "```json\n"
        + json.dumps(get_mcp_config_snippet("antigravity", clean_base, token_param or None), indent=2)
        + "\n```\n\n"
        "#### Cursor IDE:\n"
        "- **Path**: `~/.cursor/mcp.json` (or `%USERPROFILE%\\.cursor\\mcp.json` on Windows)\n"
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
        "```bash\n"
        + str(get_mcp_config_snippet("claude-code", clean_base, token_param or None))
        + "\n```\n\n"
        "### Global Directive Template:\n"
        "Save this in `GEMINI.md`, `CLAUDE.md`, or `.cursor/rules/helios.mdc` (idempotently replacing existing `<!-- HELIOS:START -->` block):\n"
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
}}

# 3. Claude Desktop Configuration (if %APPDATA%\\Claude exists or client is claude-desktop/all)
$claudeDir = Join-Path $env:APPDATA "Claude"
if ((Test-Path $claudeDir) -or "{client_norm}" -eq "claude-desktop") {{
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

# 4. Global Directive (GEMINI.md with CRLF and symlink handling)
$geminiPath = Join-Path $configDir "GEMINI.md"
$directiveText = @'
{directive}
'@

if (Test-Path $geminiPath) {{
    $resolvedPath = (Resolve-Path $geminiPath).Path
    $content = [System.IO.File]::ReadAllText($resolvedPath, [System.Text.Encoding]::UTF8)
    if ($content -match '(?s)<!-- HELIOS:START -->.*?<!-- HELIOS:END -->') {{
        $content = [regex]::Replace($content, '(?s)<!-- HELIOS:START -->.*?<!-- HELIOS:END -->', {{ param($m) $directiveText }})
    }} else {{
        $content = $directiveText + "`r`n`r`n" + $content
    }}
    [System.IO.File]::WriteAllText($resolvedPath, $content, [System.Text.Encoding]::UTF8)
}} else {{
    [System.IO.File]::WriteAllText($geminiPath, $directiveText, [System.Text.Encoding]::UTF8)
}}
Write-Host "  [OK] Global directive embedded in $geminiPath" -ForegroundColor Green

# 5. /remember Skill (~/.gemini/skills/remember/SKILL.md)
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
    role_norm = instance_role.strip().lower()
    client_norm = client.strip().lower()

    return f"""#!/usr/bin/env bash
set -euo pipefail

echo "Configuring Helios client environment for {clean_base} (role: {role_norm})..."

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

# 4. Claude Code CLI (if claude CLI binary exists in PATH)
if command -v claude >/dev/null 2>&1; then
    claude mcp add --transport sse helios "{sse_url}" >/dev/null 2>&1 || true
    echo "  [OK] Claude Code CLI MCP registered"
fi

# 5. Global Directive (GEMINI.md with symlink resolution)
GEMINI_PATH="$CONFIG_DIR/GEMINI.md"
DIRECTIVE_CONTENT="$(cat <<'HELIOS_DIRECTIVE_EOF'
{directive}
HELIOS_DIRECTIVE_EOF
)"

GEMINI_PATH="$GEMINI_PATH" DIRECTIVE="$DIRECTIVE_CONTENT" python3 - <<'PYEOF'
import os, re
path = os.environ["GEMINI_PATH"]
directive = os.environ["DIRECTIVE"]
if os.path.exists(path):
    real_path = os.path.realpath(path)
    with open(real_path, 'r', encoding='utf-8') as f:
        content = f.read()
    if re.search(r'<!-- HELIOS:START -->.*?<!-- HELIOS:END -->', content, flags=re.DOTALL):
        new_content = re.sub(
            r'<!-- HELIOS:START -->.*?<!-- HELIOS:END -->',
            lambda _: directive,
            content,
            flags=re.DOTALL,
        )
    else:
        new_content = directive + '\n\n' + content
    with open(real_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
else:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(directive)
PYEOF
echo "  [OK] Global directive embedded in $GEMINI_PATH"

# 6. /remember Skill (~/.gemini/skills/remember/SKILL.md)
SKILL_DIR="$HOME/.gemini/skills/remember"
mkdir -p "$SKILL_DIR"
cat <<'HELIOS_SKILL_EOF' > "$SKILL_DIR/SKILL.md"
{skill}
HELIOS_SKILL_EOF
echo "  [OK] /remember skill installed in $SKILL_DIR/SKILL.md"

echo ""
echo "=================================================="
echo "Helios client onboarding complete!"
echo "Action required for AI agents:"
echo "  1. Restart active IDE window or CLI agent session to load 'helios'."
echo "  2. Call recall_memories(scope='<repo>') to verify memory connection."
echo "  3. Call manage_git_webhooks(action='list') to audit push drift tracking."
echo "=================================================="
"""
