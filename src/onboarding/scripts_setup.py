"""Automated Bash and PowerShell 1-liner client setup script generators."""

import urllib.parse

from src.config import get_word_limit
from src.onboarding.templates import (
    generate_global_directive,
    generate_guard_hook_script,
    generate_remember_skill,
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
    python3 - "$target_path" "$DIRECTIVE_CONTENT" <<'PYEOF'
import os, re, sys
path = sys.argv[1]
directive = sys.argv[2]
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
MCP_URL="{mcp_url}"

python3 - "$MCP_CONFIG" "$MCP_URL" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
mcp_url = sys.argv[2]
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
    SSE_URL="{sse_url}"
    python3 - "$CURSOR_MCP" "$SSE_URL" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
sse_url = sys.argv[2]
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
        SSE_URL="{sse_url}"
        python3 - "$CLAUDE_MCP" "$SSE_URL" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
sse_url = sys.argv[2]
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
    MCP_URL="{mcp_url}"
    python3 - "$CODEX_TOML" "$MCP_URL" <<'PYEOF'
import os, re, sys
path = sys.argv[1]
mcp_url = sys.argv[2]
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
    MCP_URL="{mcp_url}"
    python3 - "$WINDSURF_MCP" "$MCP_URL" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
mcp_url = sys.argv[2]
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
        MCP_URL="{mcp_url}"
        python3 - "$VSCODE_MCP" "$MCP_URL" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
mcp_url = sys.argv[2]
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
    MCP_URL="{mcp_url}"
    python3 - "$OPENCODE_MCP" "$MCP_URL" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
mcp_url = sys.argv[2]
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
python3 - "$HOOKS_PATH" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
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


__all__ = [
    "generate_setup_bash",
    "generate_setup_powershell",
]
