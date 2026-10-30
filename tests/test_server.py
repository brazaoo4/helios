"""Integration and public re-export contract tests for the Helios composition root."""

from starlette.testclient import TestClient

import src.server
from src.server import app, recall_memories


def test_lifespan_declarative_seed_ingestion(tmp_path):
    """Verify Starlette lifespan imports declarative seed files and renames to .imported."""
    seed_file = tmp_path / "seed.yaml"
    seed_file.write_text(
        """
aliases:
  my-repo: core-app
memories:
  - scope: my-repo
    category: rule
    subject: strict-typing
    content: Enforce mypy strict mode across all Python modules.
    anchor_files:
      - pyproject.toml
""",
        encoding="utf-8",
    )

    with TestClient(app):
        assert not seed_file.exists()
        assert (tmp_path / "seed.yaml.imported").exists()
        recalled = recall_memories(scope="my-repo", query="mypy")
        assert "Enforce mypy strict mode" in recalled


def test_lifespan_auto_seed_environment(monkeypatch):
    """Verify lifespan triggers auto-seeding when HELIOS_AUTO_SEED is enabled."""
    monkeypatch.setenv("HELIOS_AUTO_SEED", "true")
    with TestClient(app):
        # Database should be seeded on startup
        recalled = recall_memories(scope="helios", query="AUDN")
        assert "AUDN" in recalled


def test_server_public_reexports_contract():
    """Verify that src.server preserves full backward compatibility via __all__."""
    expected_symbols = [
        "COLD_START_ONBOARDING_NOTICE",
        "HELIOS_INSTRUCTIONS",
        "AuthGateMiddleware",
        "HybridMCPHandler",
        "MAX_WEBHOOK_BYTES",
        "StreamableMCPHandler",
        "ToolAnnotations",
        "_detect_webhook_provider_and_verify",
        "_is_push_event",
        "_process_webhook_drift",
        "_query_health_status",
        "_read_bounded_body",
        "_scan_markdown_exports",
        "app",
        "deprecate_memory",
        "disable_repo_webhooks",
        "distill_memories",
        "enable_repo_webhooks",
        "export_bundle",
        "export_bundle_download",
        "forgejo_webhook",
        "get_client_setup_bundle",
        "git_webhook",
        "health_check",
        "hybrid_handler",
        "is_request_authenticated",
        "lifespan",
        "list_markdown_exports",
        "list_repo_webhooks",
        "manage_git_webhooks",
        "manage_scope_alias",
        "manage_server_config",
        "mcp",
        "recall_history",
        "recall_memories",
        "revalidate_memories",
        "save_memory",
        "setup_bash_script",
        "setup_instructions",
        "setup_powershell_script",
        "sse_app",
        "starlette_routes",
        "streamable_handler",
        "transport_security",
        "uninstall_bash_script",
        "uninstall_instructions",
        "uninstall_powershell_script",
        "verify_forgejo_signature",
        "verify_github_signature",
    ]

    assert hasattr(src.server, "__all__")
    assert set(expected_symbols) == set(src.server.__all__)

    for name in expected_symbols:
        assert hasattr(src.server, name), f"src.server is missing re-export for {name}"
