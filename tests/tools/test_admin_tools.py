"""Tests for FastMCP admin and operational tools (export_bundle)."""

from src.server import export_bundle, save_memory


def test_mcp_export_bundle_tool():
    save_memory(scope="infrastructure", category="fact", content="Docker subnet is 172.20.0.0/16")
    res = export_bundle()
    assert "Snapshot created:" in res
    assert "helios_portable_bundle.tar.gz" in res


def test_manage_git_webhooks_tool_validation(monkeypatch):
    from src.tools.admin import manage_git_webhooks

    # 1. Unconfigured provider
    res_unconfigured = manage_git_webhooks(action="list")
    assert "Git webhook management is not configured" in res_unconfigured

    # Set minimal webhook config to test action routing
    monkeypatch.setenv("HELIOS_GIT_TOKEN", "mock-token-xyz")
    monkeypatch.setenv("HELIOS_WEBHOOK_URL", "https://helios.example.com/webhook/git")

    # 2. Invalid action
    res_inv = manage_git_webhooks(action="invalid_action")
    assert "Invalid action 'invalid_action'" in res_inv

    # 3. Enable without repos
    res_en = manage_git_webhooks(action="enable")
    assert "Please specify one or more repository names to enable" in res_en

    # 4. Disable without repos
    res_dis = manage_git_webhooks(action="disable")
    assert "Please specify one or more repository names to disable" in res_dis


def test_export_bundle_redacts_secrets_on_failure(monkeypatch):
    from unittest.mock import patch

    with patch(
        "src.tools.admin.create_portable_archive",
        side_effect=RuntimeError("backup failed for postgres://admin:topsecret@db:5432/helios"),
    ):
        res = export_bundle()
    assert "Error generating export bundle:" in res
    assert "topsecret" not in res
    assert "[REDACTED]" in res


def test_manage_git_webhooks_list_enable_disable_results_and_errors(monkeypatch):
    from unittest.mock import patch

    from src.tools.admin import manage_git_webhooks

    monkeypatch.setenv("HELIOS_GIT_TOKEN", "ghp_" + ("a" * 36))
    monkeypatch.setenv("HELIOS_WEBHOOK_URL", "https://helios.example.com/webhook/git")

    # 1. list: empty & populated (including fork & matched scope)
    with patch("src.server.list_repo_webhooks", return_value=[]):
        assert "No eligible repositories found" in manage_git_webhooks(action="list")

    sample_list = [
        {"repo": "braz/helios", "enabled": True, "matched_scope": "helios", "is_fork": False},
        {"repo": "braz/forked", "enabled": False, "matched_scope": None, "is_fork": True},
    ]
    with patch("src.server.list_repo_webhooks", return_value=sample_list):
        res_list = manage_git_webhooks(action="list", include_forks=True)
        assert "[x] `braz/helios`" in res_list
        assert "matched Helios scope: `helios`" in res_list
        assert "[ ] `braz/forked` (fork)" in res_list

    # 2. enable: mixed enabled / already_enabled / failed & no-op
    with patch(
        "src.server.enable_repo_webhooks",
        return_value={
            "enabled": ["braz/a"],
            "already_enabled": ["braz/b"],
            "failed": [{"repo": "braz/c", "error": "HTTP 403"}],
        },
    ):
        res_en = manage_git_webhooks(action="enable", repos=["braz/a", "braz/b", "braz/c"])
        assert "Successfully enabled drift webhooks on: `braz/a`." in res_en
        assert "Already enabled: `braz/b`." in res_en
        assert "Failed to enable on: `braz/c`: HTTP 403." in res_en

    # 3. disable: mixed disabled / not_found / failed
    with patch(
        "src.server.disable_repo_webhooks",
        return_value={
            "disabled": ["braz/a"],
            "not_found": ["braz/b"],
            "failed": [{"repo": "braz/c", "error": "HTTP 500"}],
        },
    ):
        res_dis = manage_git_webhooks(action="disable", repos=["braz/a", "braz/b", "braz/c"])
        assert "Successfully disabled drift webhooks on: `braz/a`." in res_dis
        assert "No active Helios webhook found on: `braz/b`." in res_dis
        assert "Failed to disable on: `braz/c`: HTTP 500." in res_dis

    # 4. Unexpected exception redacts secrets
    secret_val = "ghp_" + ("z" * 36)
    with patch("src.server.list_repo_webhooks", side_effect=RuntimeError(f"boom {secret_val}")):
        res_err = manage_git_webhooks(action="list")
        assert "Error managing git webhooks:" in res_err
        assert secret_val not in res_err
        assert "[REDACTED]" in res_err


