"""Client configuration metadata, paths, and snippet generators across supported IDEs."""

import re
import sys
import urllib.parse
from typing import Any

from src.config import get_public_url

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


__all__ = [
    "SUPPORTED_CLIENTS",
    "get_directive_path",
    "get_mcp_config_path",
    "get_mcp_config_snippet",
    "normalize_os_platform",
    "resolve_server_base_url",
]
