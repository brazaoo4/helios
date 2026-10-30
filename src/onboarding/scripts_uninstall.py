"""Automated Bash and PowerShell 1-liner client uninstaller script generators."""


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
        python3 - "$target_path" <<'PYEOF'
import os, re, sys
target_path = sys.argv[1]
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
        python3 - "$MCP_CONFIG" <<'PYEOF'
import json, sys
mcp_path = sys.argv[1]
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
        python3 - "$HOOKS_PATH" <<'PYEOF'
import json, sys
hooks_path = sys.argv[1]
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
        python3 - "$CURSOR_MCP" <<'PYEOF'
import json, sys
cursor_path = sys.argv[1]
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
            python3 - "$CLAUDE_MCP" <<'PYEOF'
import json, sys
claude_path = sys.argv[1]
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
        python3 - "$CODEX_TOML" <<'PYEOF'
import os, re, sys
codex_path = sys.argv[1]
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
        python3 - "$WINDSURF_MCP" <<'PYEOF'
import json, sys
windsurf_path = sys.argv[1]
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
            python3 - "$VSCODE_MCP" <<'PYEOF'
import json, sys
vscode_path = sys.argv[1]
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
        python3 - "$OPENCODE_MCP" <<'PYEOF'
import json, sys
opencode_path = sys.argv[1]
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


__all__ = [
    "generate_uninstall_bash",
    "generate_uninstall_powershell",
]
