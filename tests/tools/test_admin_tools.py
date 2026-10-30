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
    monkeypatch.setenv("HELIOS_WEBHOOK_URL", "http://localhost:8000/webhook/git")

    # 2. Invalid action
    res_inv = manage_git_webhooks(action="invalid_action")
    assert "Invalid action 'invalid_action'" in res_inv

    # 3. Enable without repos
    res_en = manage_git_webhooks(action="enable")
    assert "Please specify one or more repository names to enable" in res_en

    # 4. Disable without repos
    res_dis = manage_git_webhooks(action="disable")
    assert "Please specify one or more repository names to disable" in res_dis


