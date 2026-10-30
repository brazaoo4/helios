"""Tests for FastMCP configuration tools (manage_server_config, manage_scope_alias)."""

from starlette.testclient import TestClient

from src.exporter import get_export_dir
from src.server import (
    app,
    manage_scope_alias,
    manage_server_config,
    recall_memories,
    save_memory,
)


def test_manage_scope_alias_mcp_tool():
    # List when empty
    assert "No scope aliases configured" in manage_scope_alias(action="list")

    # Set alias
    res_set = manage_scope_alias(alias="frontend-v2", canonical_scope="web", action="set")
    assert "Alias 'frontend-v2' mapped to canonical scope 'web'" in res_set

    # List when populated
    res_list = manage_scope_alias(action="list")
    assert "`frontend-v2` -> `web`" in res_list

    # Verify save_memory and recall_memories use the alias
    save_memory(scope="frontend-v2", category="fact", content="Uses Tailwind CSS v4", subject="styling")
    recalled = recall_memories(scope="web", query="Tailwind")
    assert "Uses Tailwind CSS v4" in recalled

    # Remove alias
    res_rem = manage_scope_alias(alias="frontend-v2", action="remove")
    assert "Alias 'frontend-v2' removed" in res_rem
    assert "not found" in manage_scope_alias(alias="frontend-v2", action="remove")


def test_manage_scope_alias_rename_action():
    # Create memory in source scope
    save_memory(scope="ticket-tracker", category="fact", content="Legacy ticket API port 8080", subject="api-port")
    assert (get_export_dir() / "ticket-tracker.md").exists()

    # Call manage_scope_alias with action="rename"
    res = manage_scope_alias(alias="ticket-tracker", canonical_scope="ticketera", action="rename")
    assert "migrated to 'ticketera'" in res
    assert "Alias registered" in res

    # Check that export was synced and ghost file was removed
    assert not (get_export_dir() / "ticket-tracker.md").exists()
    assert (get_export_dir() / "ticketera.md").exists()

    # Recalling under ticketera returns the memory
    recalled = recall_memories(scope="ticketera", query="8080")
    assert "Legacy ticket API port 8080" in recalled


def test_manage_scope_alias_list_with_statistics():
    # Save active and stale memories
    save_memory(
        scope="infra",
        category="fact",
        content="Primary ingress IP 10.0.0.1",
        subject="ingress",
        anchor_files=["traefik.yaml"],
    )
    save_memory(scope="infra", category="rule", content="Use TLS 1.3 only", subject="tls")

    # Flag traefik.yaml as stale
    with TestClient(app) as client:
        hook_payload = {
            "repository": {"name": "infra"},
            "commits": [{"modified": ["traefik.yaml"]}],
            "after": "c001cafe",
        }
        res = client.post("/webhook/git", json=hook_payload)
        assert res.status_code == 200

    # Set alias
    manage_scope_alias(alias="homelab", canonical_scope="infra", action="set")

    # List aliases and statistics
    list_res = manage_scope_alias(action="list")
    assert "### Configured Scope Aliases" in list_res
    assert "`homelab` -> `infra`" in list_res
    assert "### Active Scopes in Memory" in list_res
    assert "- `infra` (1 active, 1 stale) <- aliases: `homelab`" in list_res


def test_manage_server_config_list(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "prod-secret-key")
    monkeypatch.setenv("HELIOS_GIT_TOKEN", "ghp_secrettoken123456789")

    res = manage_server_config(action="list")
    assert "### Live Server Configuration (Day-2 Management)" in res
    assert "| `HELIOS_WORD_LIMIT` | `25` | `default` |" in res
    assert "| `HELIOS_GIT_TOKEN` | •••••••• (configured) | `env` |" in res
    # Security: raw git token must never be exposed
    assert "ghp_secrettoken123456789" not in res

    # Security env status indicators
    assert "### Security Environment Status (Read-Only via env)" in res
    assert "`HELIOS_API_KEY`: enabled (configured via env)" in res
    assert "prod-secret-key" not in res
    assert "`HELIOS_WEBHOOK_SECRET`: disabled" in res


def test_manage_server_config_set_and_reset():
    # 1. 35-word memory initially fails because default limit is 25 words
    long_content = " ".join([f"word{i}" for i in range(35)])
    res_err1 = save_memory(scope="testscope", category="fact", content=long_content)
    assert "Error saving memory" in res_err1
    assert "exceeds 25-word limit" in res_err1

    # 2. Increase word limit to 40 live in SQLite
    set_res = manage_server_config(action="set", key="HELIOS_WORD_LIMIT", value="40")
    assert "updated live in SQLite to '40'" in set_res

    # 3. Now the 35-word memory saves successfully
    save_res = save_memory(scope="testscope", category="fact", content=long_content, subject="longmem")
    assert "Memory #" in save_res

    # 4. Reset word limit back to default
    reset_res = manage_server_config(action="reset", key="HELIOS_WORD_LIMIT")
    assert "reset in SQLite override" in reset_res
    assert "default ('25')" in reset_res

    # 5. Saving another 35-word memory is rejected again
    long_content_2 = " ".join([f"token{i}" for i in range(35)])
    res_err2 = save_memory(scope="testscope", category="fact", content=long_content_2)
    assert "Error saving memory" in res_err2
    assert "exceeds 25-word limit" in res_err2

    # 6. Validation bounds error
    err_low = manage_server_config(action="set", key="HELIOS_WORD_LIMIT", value="4")
    assert "Validation error" in err_low
    assert "between 5 and 200" in err_low

    err_high = manage_server_config(action="set", key="HELIOS_WORD_LIMIT", value="250")
    assert "Validation error" in err_high
    assert "between 5 and 200" in err_high

    # 7. Git provider validation
    err_prov = manage_server_config(action="set", key="HELIOS_GIT_PROVIDER", value="svn")
    assert "Validation error" in err_prov
    assert "must be one of" in err_prov

    # 8. Setting sensitive token masks it in return message
    tok_res = manage_server_config(action="set", key="HELIOS_GIT_TOKEN", value="my-secret-pat")
    assert "updated live in SQLite to '•••••••• (configured)'" in tok_res
    assert "my-secret-pat" not in tok_res

    # 9. Security guardrails reject locked security settings
    sec_set = manage_server_config(action="set", key="HELIOS_API_KEY", value="newkey")
    assert "Security violation" in sec_set
    assert "locked security setting" in sec_set

    sec_reset = manage_server_config(action="reset", key="HELIOS_WEBHOOK_SECRET")
    assert "Security violation" in sec_reset

    # 10. Unknown setting
    unk_res = manage_server_config(action="set", key="NONEXISTENT_SETTING", value="val")
    assert "Error: Unknown setting" in unk_res
