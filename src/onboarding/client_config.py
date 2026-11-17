"""Client configuration metadata, paths, and snippet generators across supported IDEs."""

import re
import sys
import urllib.parse
from typing import Any

from src.config import get_allowed_origins, get_public_url, validate_http_url

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

VALID_CLIENTS: tuple[str, ...] = SUPPORTED_CLIENTS + ("all",)
VALID_ROLES: tuple[str, ...] = ("workstation", "server-cli")


def validate_onboarding_params(
    instance_role: str | None = None,
    client: str | None = None,
) -> tuple[str, str]:
    """Validate and normalize instance_role and client against allowed identifiers."""
    norm_role = (instance_role or "workstation").strip().lower()
    if norm_role not in VALID_ROLES:
        raise ValueError(
            f"Invalid instance_role: '{instance_role}'. Must be one of: {', '.join(VALID_ROLES)}"
        )
    norm_client = (client or "all").strip().lower()
    if norm_client not in VALID_CLIENTS:
        raise ValueError(
            f"Invalid client: '{client}'. Must be one of: {', '.join(VALID_CLIENTS)}"
        )
    return norm_role, norm_client


def escape_ps_single_quote(s: str) -> str:
    """Escape string for single-quoted PowerShell string literal."""
    return s.replace("'", "''")


def escape_bash_single_quote(s: str) -> str:
    """Escape string for single-quoted Bash string literal."""
    return s.replace("'", "'\\''")


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
        if not host or not re.fullmatch(r"[a-zA-Z0-9._:\[\]-]+", host):
            host = "localhost:8000"

        candidate = f"{proto}://{host}".rstrip("/")
        try:
            validated = validate_http_url(candidate, allow_loopback=True)
        except ValueError:
            return "http://localhost:8000"

        allowed = get_allowed_origins()
        if allowed and "*" not in allowed:
            allowed_netlocs = {(urllib.parse.urlsplit(o).netloc or o).lower() for o in allowed}
            allowed_hosts = {
                (urllib.parse.urlsplit(o).hostname or o.split(":")[0]).lower() for o in allowed
            }
            cand_parsed = urllib.parse.urlsplit(validated)
            cand_host = (cand_parsed.hostname or host.split(":")[0]).lower()
            if (
                host.lower() not in allowed_netlocs
                and cand_host not in allowed_hosts
                and cand_host not in ("localhost", "127.0.0.1")
            ):
                return "http://localhost:8000"

        return validated

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
    clean_tok = token.strip() if token else ""
    token_suffix = ""
    if clean_tok:
        if clean_tok == "<YOUR_HELIOS_API_KEY>":
            token_suffix = f"?token={clean_tok}"
        else:
            token_suffix = f"?token={urllib.parse.quote(clean_tok, safe='')}"

    clean_mcp_url = f"{clean_base}/mcp"
    clean_sse_url = f"{clean_base}/sse"
    mcp_url = f"{clean_mcp_url}{token_suffix}"
    sse_url = f"{clean_sse_url}{token_suffix}"
    auth_headers = {"Authorization": f"Bearer {clean_tok}"} if clean_tok else None

    if c == "antigravity":
        return {
            "mcpServers": {
                "helios": {
                    "url": mcp_url,
                }
            }
        }
    elif c == "cursor":
        cursor_entry: dict[str, Any] = {"url": clean_sse_url}
        if auth_headers:
            cursor_entry["headers"] = auth_headers
        return {
            "mcpServers": {
                "helios": cursor_entry,
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
        if clean_tok:
            return f'claude mcp add --transport sse helios {clean_sse_url} --header "Authorization: Bearer {clean_tok}"'
        return f"claude mcp add --transport sse helios {clean_sse_url}"
    elif c == "codex":
        return f'[mcp_servers.helios]\nurl = "{mcp_url}"'
    elif c == "windsurf":
        windsurf_entry: dict[str, Any] = {"serverUrl": clean_mcp_url}
        if auth_headers:
            windsurf_entry["headers"] = auth_headers
        return {
            "mcpServers": {
                "helios": windsurf_entry,
            }
        }
    elif c == "vscode":
        vscode_entry: dict[str, Any] = {"type": "http", "url": clean_mcp_url}
        if auth_headers:
            vscode_entry["headers"] = auth_headers
        return {
            "servers": {
                "helios": vscode_entry,
            }
        }
    elif c == "opencode":
        opencode_entry: dict[str, Any] = {
            "type": "remote",
            "url": clean_mcp_url,
            "enabled": True,
        }
        if auth_headers:
            opencode_entry["headers"] = auth_headers
        return {
            "mcp": {
                "helios": opencode_entry,
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
    "VALID_CLIENTS",
    "VALID_ROLES",
    "escape_bash_single_quote",
    "escape_ps_single_quote",
    "get_directive_path",
    "get_mcp_config_path",
    "get_mcp_config_snippet",
    "normalize_os_platform",
    "resolve_server_base_url",
    "validate_onboarding_params",
]
