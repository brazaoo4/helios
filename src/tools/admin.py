"""FastMCP snapshot export, onboarding bundle, and Git webhook management tools."""

import os
import sys
from typing import Annotated, Any, Literal

from pydantic import Field

from src import webhooks as _webhooks_mod
from src.config import get_git_token, get_webhook_url
from src.exporter import create_portable_archive
from src.onboarding import generate_client_bundle, resolve_server_base_url
from src.tools.base import ToolAnnotations, mcp


def _get_webhook_func(name: str) -> Any:
    server_mod = sys.modules.get("src.server")
    if server_mod is not None and hasattr(server_mod, name):
        return getattr(server_mod, name)
    return getattr(_webhooks_mod, name)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def export_bundle() -> str:
    """
    Generate a complete, portable archive snapshot (helios_portable_bundle.tar.gz)
    using the SQLite Online Backup API, bundling the DB and all Markdown exports.
    """
    try:
        archive_path = create_portable_archive()
        size_kb = round(os.path.getsize(archive_path) / 1024, 2)
        return f"Snapshot created: {archive_path} ({size_kb} KB)."
    except Exception as exc:
        return f"Error generating export bundle: {exc}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def manage_git_webhooks(
    action: Annotated[
        Literal["list", "enable", "disable"],
        Field(
            description="Action to perform: 'list' (display repos and drift hook status), 'enable' (attach drift webhook), or 'disable' (remove drift webhook)."
        ),
    ] = "list",
    repos: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="List of repository names (e.g. ['braz/helios', 'braz/homelab']) to enable or disable.",
        ),
    ] = None,
    include_forks: Annotated[
        bool,
        Field(
            default=False,
            description="Whether to include forked repositories when listing.",
        ),
    ] = False,
) -> str:
    """
    Manage Git repository push drift detection webhooks across Forgejo, Gitea, GitHub, or GitLab.
    """
    token = get_git_token()
    webhook_url = get_webhook_url()

    if not token or not webhook_url:
        missing = []
        if not token:
            missing.append("HELIOS_GIT_TOKEN")
        if not webhook_url:
            missing.append("HELIOS_WEBHOOK_URL")

        sample_url = webhook_url or f"{resolve_server_base_url()}/webhook/git"
        return (
            f"Git webhook management is not configured on this server (missing: {', '.join(missing)}).\n\n"
            "### Manual Configuration (Git Web UI):\n"
            f"1. Open repository settings -> Webhooks -> Add Webhook.\n"
            f"2. Payload URL: `{sample_url}`\n"
            "3. Content type: `application/json`\n"
            f"4. Secret: Set your `HELIOS_WEBHOOK_SECRET`.\n"
            "5. Trigger: Push events.\n\n"
            "### Conversational Automation Configuration:\n"
            "Configure the following in your Helios `.env` and restart Helios:\n"
            "```bash\n"
            "HELIOS_GIT_PROVIDER=forgejo  # or gitea, github, gitlab\n"
            "HELIOS_GIT_API_URL=https://git.example.com\n"
            "HELIOS_GIT_TOKEN=your_personal_access_token\n"
            f"HELIOS_WEBHOOK_URL={sample_url}\n"
            "```"
        )

    try:
        act = (action or "list").strip().lower()
        if act == "list":
            candidates = _get_webhook_func("list_repo_webhooks")(
                include_forks=include_forks
            )
            if not candidates:
                return "No eligible repositories found owned by the authenticated Git user."

            lines = ["### Git Repository Drift Webhook Status\n"]
            for c in candidates:
                mark = "[x]" if c["enabled"] else "[ ]"
                status_str = (
                    "drift webhook active"
                    if c["enabled"]
                    else "drift webhook not configured"
                )
                scope_str = (
                    f", matched Helios scope: `{c['matched_scope']}`"
                    if c.get("matched_scope")
                    else ""
                )
                fork_str = " (fork)" if c.get("is_fork") else ""
                lines.append(
                    f"- {mark} `{c['repo']}`{fork_str} ({status_str}{scope_str})"
                )

            lines.append(
                "\n> **Agent Instruction**: Show this checklist to the user and ask which repositories "
                "they want to enable before calling `manage_git_webhooks(action='enable', repos=[...])`."
            )
            return "\n".join(lines)

        elif act == "enable":
            if not repos:
                return "Error: Please specify one or more repository names to enable webhooks on (e.g., repos=['owner/repo'])."
            res = _get_webhook_func("enable_repo_webhooks")(repos=repos)
            parts = []
            if res["enabled"]:
                parts.append(
                    f"Successfully enabled drift webhooks on: {', '.join(f'`{r}`' for r in res['enabled'])}."
                )
            if res["already_enabled"]:
                parts.append(
                    f"Already enabled: {', '.join(f'`{r}`' for r in res['already_enabled'])}."
                )
            if res["failed"]:
                err_strs = [f"`{f['repo']}`: {f['error']}" for f in res["failed"]]
                parts.append(f"Failed to enable on: {'; '.join(err_strs)}.")
            return "\n".join(parts) if parts else "No changes made."

        elif act == "disable":
            if not repos:
                return "Error: Please specify one or more repository names to disable webhooks on (e.g., repos=['owner/repo'])."
            res = _get_webhook_func("disable_repo_webhooks")(repos=repos)
            parts = []
            if res["disabled"]:
                parts.append(
                    f"Successfully disabled drift webhooks on: {', '.join(f'`{r}`' for r in res['disabled'])}."
                )
            if res["not_found"]:
                parts.append(
                    f"No active Helios webhook found on: {', '.join(f'`{r}`' for r in res['not_found'])}."
                )
            if res["failed"]:
                err_strs = [f"`{f['repo']}`: {f['error']}" for f in res["failed"]]
                parts.append(f"Failed to disable on: {'; '.join(err_strs)}.")
            return "\n".join(parts) if parts else "No changes made."

        else:
            return f"Invalid action '{action}'. Must be 'list', 'enable', or 'disable'."
    except Exception as exc:
        return f"Error managing git webhooks: {exc}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def get_client_setup_bundle(
    client: Annotated[
        Literal[
            "antigravity",
            "cursor",
            "claude-desktop",
            "claude-code",
            "codex",
            "windsurf",
            "vscode",
            "opencode",
            "all",
        ],
        Field(description="Target client environment to configure."),
    ] = "all",
    os_platform: Annotated[
        Literal["windows", "linux", "macos", "auto"],
        Field(description="Target operating system for config file paths."),
    ] = "auto",
    instance_role: Annotated[
        Literal["workstation", "server-cli"],
        Field(
            description="Role of this machine ('workstation' for IDE/laptop or 'server-cli' for headless host with strict log-truncation rules)."
        ),
    ] = "workstation",
    action: Annotated[
        Literal["install_or_update", "switch_role", "uninstall"],
        Field(
            description="Lifecycle action: 'install_or_update' (idempotently set or refresh client config and directive blocks), 'switch_role' (change machine role between 'workstation' and 'server-cli'), or 'uninstall' (instructions to cleanly remove Helios from MCP config, strip the HELIOS marker block, and remove the /remember skill)."
        ),
    ] = "install_or_update",
) -> str:
    """
    Retrieve client configuration snippets, global directives (GEMINI.md, AGENTS.md, CLAUDE.md, etc.), and the /remember skill definition.
    """
    base_url = resolve_server_base_url()
    return generate_client_bundle(
        client=client,
        os_platform=os_platform,
        instance_role=instance_role,
        base_url=base_url,
        action=action,
    )


__all__ = [
    "export_bundle",
    "get_client_setup_bundle",
    "manage_git_webhooks",
]
