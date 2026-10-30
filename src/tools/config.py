"""FastMCP server settings and scope alias management tools."""

from typing import Annotated, Literal

from pydantic import Field

from src.config import (
    LOCKED_SECURITY_KEYS,
    MUTABLE_SETTINGS,
    get_allowed_origins,
    get_api_key,
    get_memory_data_dir,
    get_webhook_secret,
    resolve_setting_with_source,
    validate_setting_value,
)
from src.db import (
    delete_runtime_setting,
    get_scope_statistics,
    list_aliases,
    migrate_scope,
    remove_alias,
    set_alias,
    set_runtime_setting,
)
from src.exporter import sync_markdown_exports
from src.tools.base import ToolAnnotations, mcp


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    )
)
def manage_scope_alias(
    alias: Annotated[
        str,
        Field(
            default="",
            description="Source alias or folder name (e.g., 'ticket-tracker').",
        ),
    ] = "",
    canonical_scope: Annotated[
        str,
        Field(
            default="",
            description="Target canonical scope name (e.g., 'ticketera').",
        ),
    ] = "",
    action: Annotated[
        Literal["set", "remove", "list", "rename"],
        Field(
            default="set",
            description="Action to perform: 'set' (map alias), 'remove' (delete alias), 'list' (show all), or 'rename' (migrate all memories to new scope and register alias).",
        ),
    ] = "set",
) -> str:
    """
    Manage project and folder aliases mapping to canonical memory scopes.
    - action='set': Maps alias -> canonical_scope (e.g. 'frontend-v2' -> 'web').
    - action='remove': Deletes an existing alias mapping.
    - action='list': Returns all current alias-to-scope mappings.
    - action='rename': Migrates all memories from alias to canonical_scope and registers alias.
    """
    try:
        act = (action or "").strip().lower()
        if act == "set":
            set_alias(alias, canonical_scope)
            mappings = list_aliases()
            clean_alias = (
                alias.strip().replace("\\", "/").rstrip("/").split("/")[-1].lower()
            )
            clean_alias = clean_alias.removesuffix(".git")
            resolved_target = mappings.get(clean_alias, canonical_scope.strip().lower())
            return f"Alias '{clean_alias}' mapped to canonical scope '{resolved_target}'."
        elif act in ("remove", "delete"):
            removed = remove_alias(alias)
            if removed:
                return f"Alias '{alias.strip().lower()}' removed."
            return f"Alias '{alias.strip().lower()}' not found."
        elif act == "list":
            mappings = list_aliases()
            scope_stats = get_scope_statistics()
            lines = ["### Configured Scope Aliases"]
            if not mappings:
                lines.append("No scope aliases configured.")
            else:
                for k, v in mappings.items():
                    lines.append(f"- `{k}` -> `{v}`")

            lines.append("")
            lines.append("### Active Scopes in Memory")
            if not scope_stats:
                lines.append("No scopes found in memory.")
            else:
                for s in scope_stats:
                    alias_note = (
                        f" <- aliases: {', '.join(f'`{a}`' for a in s['aliases'])}"
                        if s["aliases"]
                        else ""
                    )
                    lines.append(
                        f"- `{s['scope']}` ({s['active_count']} active, {s['stale_count']} stale){alias_note}"
                    )

            return "\n".join(lines)
        elif act == "rename":
            res = migrate_scope(
                from_scope=alias, to_scope=canonical_scope, register_alias=True
            )
            sync_markdown_exports()
            return (
                f"Scope '{res['from_scope']}' migrated to '{res['to_scope']}' "
                f"({res['migrated_count']} memories moved). Alias registered."
            )
        else:
            return (
                f"Invalid action '{action}'. Must be 'set', 'remove', 'list', or 'rename'."
            )
    except Exception as exc:
        return f"Error managing scope alias: {exc}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def manage_server_config(
    action: Annotated[
        Literal["list", "set", "reset"],
        Field(
            description="Action: 'list' (show all configurable settings, active values, and source: db/env/default), 'set' (override a setting live in SQLite without restarting), or 'reset' (delete SQLite override and revert to env/default)."
        ),
    ] = "list",
    key: Annotated[
        str,
        Field(
            default="",
            description="Setting name to modify or reset (e.g., 'HELIOS_WORD_LIMIT', 'HELIOS_EPISODIC_TTL_DAYS', 'HELIOS_GIT_PROVIDER', 'HELIOS_GIT_API_URL', 'HELIOS_GIT_TOKEN', 'HELIOS_WEBHOOK_URL', 'HELIOS_PUBLIC_URL').",
        ),
    ] = "",
    value: Annotated[
        str, Field(default="", description="New value to apply when action='set'.")
    ] = "",
) -> str:
    """
    Manage live Day-2 Helios server configuration settings in SQLite without restarting the container.
    """
    act = (action or "list").strip().lower()

    if act == "list":
        lines = [
            "### Live Server Configuration (Day-2 Management)",
            "",
            "| Setting | Active Value | Source | Description |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for k in sorted(MUTABLE_SETTINGS.keys()):
            val, src = resolve_setting_with_source(k)
            meta = MUTABLE_SETTINGS[k]
            if meta.get("sensitive"):
                display_val = "•••••••• (configured)" if val else "(unset)"
            else:
                display_val = (
                    f"`{val}`" if (val != "" and val is not None) else "(unset)"
                )
            lines.append(f"| `{k}` | {display_val} | `{src}` | {meta['description']} |")

        api_key_status = (
            "enabled (configured via env)" if get_api_key() else "disabled (open mode)"
        )
        hook_secret_status = (
            "enabled (configured via env)" if get_webhook_secret() else "disabled"
        )
        origins_str = ", ".join(get_allowed_origins())

        lines.extend(
            [
                "",
                "### Security Environment Status (Read-Only via env)",
                f"- `HELIOS_API_KEY`: {api_key_status}",
                f"- `HELIOS_WEBHOOK_SECRET`: {hook_secret_status}",
                f"- `HELIOS_ALLOWED_ORIGINS`: `{origins_str}`",
                f"- `MEMORY_DATA_DIR`: `{get_memory_data_dir()}`",
            ]
        )
        return "\n".join(lines)

    elif act == "set":
        if not key.strip():
            return "Error: 'key' is required when action='set'."
        k = key.strip().upper()
        if k in LOCKED_SECURITY_KEYS:
            return (
                f"Security violation: '{k}' is a locked security setting and cannot be modified at runtime. "
                "It must be configured strictly via server environment variables."
            )
        if k not in MUTABLE_SETTINGS:
            return f"Error: Unknown setting '{k}'. Configurable settings are: {', '.join(sorted(MUTABLE_SETTINGS.keys()))}."

        try:
            valid_val = validate_setting_value(k, value)
        except ValueError as exc:
            return f"Validation error for '{k}': {exc}"

        set_runtime_setting(k, str(valid_val) if valid_val is not None else "")
        extra_note = ""
        if k in ("HELIOS_GIT_API_URL", "HELIOS_GIT_PROVIDER"):
            if delete_runtime_setting("HELIOS_GIT_TOKEN"):
                extra_note = " Stored runtime HELIOS_GIT_TOKEN was invalidated for safety; please re-set if needed."

        display_val = (
            "•••••••• (configured)"
            if MUTABLE_SETTINGS[k].get("sensitive") and valid_val
            else valid_val
        )
        return f"Setting '{k}' updated live in SQLite to '{display_val}'. Effective immediately without restarting.{extra_note}"

    elif act == "reset":
        if not key.strip():
            return "Error: 'key' is required when action='reset'."
        k = key.strip().upper()
        if k in LOCKED_SECURITY_KEYS:
            return f"Security violation: '{k}' is a locked security setting and cannot be modified at runtime."
        if k not in MUTABLE_SETTINGS:
            return f"Error: Unknown setting '{k}'. Configurable settings are: {', '.join(sorted(MUTABLE_SETTINGS.keys()))}."

        deleted = delete_runtime_setting(k)
        val, src = resolve_setting_with_source(k)
        meta = MUTABLE_SETTINGS[k]
        display_val = (
            "•••••••• (configured)"
            if meta.get("sensitive") and val
            else (val if val is not None else "(unset)")
        )
        if deleted:
            return f"Setting '{k}' reset in SQLite override. Active value reverted to {src} ('{display_val}')."
        return f"Setting '{k}' had no SQLite override. Current value is '{display_val}' from {src}."

    else:
        return f"Invalid action '{action}'. Must be 'list', 'set', or 'reset'."


__all__ = [
    "manage_scope_alias",
    "manage_server_config",
]
