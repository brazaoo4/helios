import hashlib
import hmac
import json
import tarfile
from io import BytesIO
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from src.db import init_db, set_alias
from src.exporter import get_export_dir
from src.server import (
    app,
    deprecate_memory,
    export_bundle,
    manage_scope_alias,
    manage_server_config,
    mcp,
    recall_history,
    recall_memories,
    revalidate_memories,
    save_memory,
)


@pytest.fixture(autouse=True)
def setup_server_env(tmp_path, monkeypatch):
    """
    Isolates data directory to a temporary path and resets environment before every test.
    """
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HELIOS_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("HELIOS_API_KEY", raising=False)
    monkeypatch.delenv("HELIOS_WORD_LIMIT", raising=False)
    init_db()


# --- 1. Healthcheck, Redaction & Lifespan Seeding ---

def test_health_endpoint_open_mode():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["service"] == "helios"
        assert data["database"]["connected"] is True
        assert data["database"]["journal_mode"] == "wal"
        assert data["database"]["active_memories"] == 0


def test_health_endpoint_redaction_when_api_key_set(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "super-secret-api-key")

    with TestClient(app) as client:
        # 1. Unauthenticated request -> 200 minimal JSON (no database telemetry)
        res_unauth = client.get("/health")
        assert res_unauth.status_code == 200
        assert res_unauth.json() == {"status": "healthy", "service": "helios"}
        assert "database" not in res_unauth.json()

        # 2. Authenticated via Bearer header -> full telemetry
        res_bearer = client.get(
            "/health",
            headers={"Authorization": "Bearer super-secret-api-key"},
        )
        assert res_bearer.status_code == 200
        data_bearer = res_bearer.json()
        assert "database" in data_bearer
        assert data_bearer["database"]["journal_mode"] == "wal"
        assert data_bearer["database"]["active_memories"] == 0

        # 3. Authenticated via ?token= query param -> full telemetry
        res_token = client.get("/health?token=super-secret-api-key")
        assert res_token.status_code == 200
        assert "database" in res_token.json()


def test_lifespan_declarative_seed_ingestion(tmp_path):
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


# --- 2. AuthGateMiddleware (Zero-Trust Security) ---

def test_auth_gate_middleware(monkeypatch):
    api_key = "zero-trust-token-999"
    monkeypatch.setenv("HELIOS_API_KEY", api_key)
    save_memory(scope="global", category="rule", content="Always authenticate public endpoints")

    with TestClient(app) as client:
        # Missing token -> 401
        res_missing = client.get("/export/markdown")
        assert res_missing.status_code == 401

        # Invalid Bearer token -> 401
        res_invalid_bearer = client.get(
            "/export/markdown",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert res_invalid_bearer.status_code == 401

        # Invalid query token -> 401
        res_invalid_query = client.get("/export/markdown?token=wrong-token")
        assert res_invalid_query.status_code == 401

        # Valid Bearer header -> 200
        res_valid_bearer = client.get(
            "/export/markdown",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert res_valid_bearer.status_code == 200
        assert "exports" in res_valid_bearer.json()

        # Valid ?token= query parameter -> 200
        res_valid_query = client.get(f"/export/markdown?token={api_key}")
        assert res_valid_query.status_code == 200
        assert "exports" in res_valid_query.json()

        # MCP /mcp endpoint requires auth when HELIOS_API_KEY is set
        res_mcp_unauth = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert res_mcp_unauth.status_code == 401


# --- 3. FastMCP Core Tools, Cold Start & Dynamic Scope Alias Tool ---

def test_cold_start_onboarding_signal():
    # Database is completely empty on initial fixture setup
    recalled_cold = recall_memories(scope="webapp")
    assert "COLD START ONBOARDING" in recalled_cold
    assert "README.md" in recalled_cold
    assert "package.json" in recalled_cold

    # Once at least one active memory exists in the DB, empty scope query does NOT show cold start banner
    save_memory(scope="global", category="rule", content="Baseline global rule")
    recalled_non_empty = recall_memories(scope="other_scope", include_global=False)
    assert "COLD START ONBOARDING" not in recalled_non_empty
    assert "No active memories found for scope 'other_scope'." in recalled_non_empty


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


def test_mcp_tools_lifecycle():
    set_alias("Infra-Repo", "infrastructure")

    # 1. Add (Create)
    res_save = save_memory(
        scope="Infra-Repo",
        category="fact",
        content="Metrics monitoring port is 8090",
        subject="metrics-port",
        anchor_files=["stacks/monitoring/compose.yaml"],
    )
    assert "created in scope 'infrastructure'" in res_save

    # 2. Recall
    recalled = recall_memories(scope="infrastructure", query="metrics")
    assert "8090" in recalled
    assert "[metrics-port]" in recalled

    # 3. No-op (Duplicate detection)
    res_noop = save_memory(
        scope="infrastructure",
        category="fact",
        content="Metrics monitoring port is 8090",
        subject="metrics-port",
    )
    assert "No-op" in res_noop

    # 4. Update / Slot Supersede
    res_update = save_memory(
        scope="infrastructure",
        category="fact",
        content="Metrics monitoring port changed to 8091",
        subject="metrics-port",
    )
    assert "superseding #1" in res_update

    # 5. Verify old fact is superseded and new fact is active
    recalled_updated = recall_memories(scope="infrastructure", query="metrics")
    assert "8091" in recalled_updated
    assert "8090" not in recalled_updated

    # 6. Deprecate
    res_deprecate = deprecate_memory(memory_id=2, reason="migrated to prometheus")
    assert "deprecated (archived)" in res_deprecate

    # 7. Recall should now find nothing active
    recalled_empty = recall_memories(scope="infrastructure", query="metrics")
    assert "No active memories found" in recalled_empty

    # 8. Recall history should list both superseded (#1) and archived (#2) entries
    history_out = recall_history(scope="infrastructure")
    assert "`#1` [superseded -> `#2`]" in history_out
    assert "`#2` [archived]" in history_out


def test_mcp_save_word_limit_guardrail():
    long_content = " ".join(["word"] * 26)
    res = save_memory(scope="infrastructure", category="fact", content=long_content)
    assert "Error saving memory" in res
    assert "exceeds 25-word limit" in res


def test_mcp_export_bundle_tool():
    save_memory(scope="infrastructure", category="fact", content="Docker subnet is 172.20.0.0/16")
    res = export_bundle()
    assert "Snapshot created:" in res
    assert "helios_portable_bundle.tar.gz" in res


# --- 4. Universal Git Webhook Adapter (`POST /webhook/git` & `POST /webhook/forgejo`) ---

def test_multi_provider_webhook_verification(monkeypatch):
    secret = "secret-token-1234"
    monkeypatch.setenv("HELIOS_WEBHOOK_SECRET", secret)
    # Also set HELIOS_API_KEY to verify that /webhook/* is exempt from AuthGateMiddleware
    monkeypatch.setenv("HELIOS_API_KEY", "unrelated-api-key")

    payload = {
        "repository": {"name": "infrastructure"},
        "commits": [{"modified": ["compose.yaml"]}],
        "after": "c1a2b3c4d5",
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    hex_digest = hmac.new(secret.encode("utf-8"), msg=raw_bytes, digestmod=hashlib.sha256).hexdigest()

    with TestClient(app) as client:
        # 1. Missing signature -> 401
        res_missing = client.post("/webhook/git", content=raw_bytes)
        assert res_missing.status_code == 401

        # 2. GitHub SHA-256 verification (valid & invalid)
        res_gh_invalid = client.post(
            "/webhook/git",
            content=raw_bytes,
            headers={"X-Hub-Signature-256": "sha256=invalid", "X-GitHub-Event": "push"},
        )
        assert res_gh_invalid.status_code == 401

        res_gh_valid = client.post(
            "/webhook/git",
            content=raw_bytes,
            headers={"X-Hub-Signature-256": f"sha256={hex_digest}", "X-GitHub-Event": "push"},
        )
        assert res_gh_valid.status_code == 200
        assert res_gh_valid.json()["provider"] == "github"
        assert res_gh_valid.json()["status"] == "processed"

        # 3. Forgejo / Gitea HMAC verification (valid & invalid on both /webhook/git and /webhook/forgejo)
        res_fj_invalid = client.post(
            "/webhook/forgejo",
            content=raw_bytes,
            headers={"X-Forgejo-Signature": "invalid-hex-digest", "X-Forgejo-Event": "push"},
        )
        assert res_fj_invalid.status_code == 401

        res_fj_valid = client.post(
            "/webhook/forgejo",
            content=raw_bytes,
            headers={"X-Forgejo-Signature": hex_digest, "X-Forgejo-Event": "push"},
        )
        assert res_fj_valid.status_code == 200
        assert res_fj_valid.json()["provider"] == "forgejo"
        assert res_fj_valid.json()["status"] == "processed"

        # 4. GitLab token verification (valid & invalid)
        res_gl_invalid = client.post(
            "/webhook/git",
            content=raw_bytes,
            headers={"X-Gitlab-Token": "wrong-token", "X-Gitlab-Event": "Push Hook"},
        )
        assert res_gl_invalid.status_code == 401

        res_gl_valid = client.post(
            "/webhook/git",
            content=raw_bytes,
            headers={"X-Gitlab-Token": secret, "X-Gitlab-Event": "Push Hook"},
        )
        assert res_gl_valid.status_code == 200
        assert res_gl_valid.json()["provider"] == "gitlab"
        assert res_gl_valid.json()["status"] == "processed"

        # 5. Null commits list / empty commits graceful handling
        null_commits_payload = json.dumps({"repository": {"name": "infrastructure"}, "commits": None}).encode("utf-8")
        null_sig = "sha256=" + hmac.new(secret.encode("utf-8"), msg=null_commits_payload, digestmod=hashlib.sha256).hexdigest()
        res_null_commits = client.post(
            "/webhook/git",
            content=null_commits_payload,
            headers={"X-Hub-Signature-256": null_sig, "X-GitHub-Event": "push"},
        )
        assert res_null_commits.status_code == 200
        assert res_null_commits.json()["commits_evaluated"] == 0


def test_webhook_fail_closed_and_size_limit(monkeypatch):
    monkeypatch.setenv("HELIOS_REQUIRE_WEBHOOK_SECRET", "true")
    monkeypatch.delenv("HELIOS_WEBHOOK_SECRET", raising=False)

    with TestClient(app) as client:
        res_no_secret = client.post("/webhook/git", content=b"{}")
        assert res_no_secret.status_code == 503

        # Over 1MB payload -> 413
        oversized = b"x" * (1_048_576 + 10)
        res_large = client.post("/webhook/git", content=oversized)
        assert res_large.status_code == 413


def test_webhook_drift_detection(monkeypatch):
    secret = "webhook-key"
    monkeypatch.setenv("HELIOS_WEBHOOK_SECRET", secret)

    # Seed memory anchored to stacks/monitoring/compose.yaml
    save_memory(
        scope="infrastructure",
        category="fact",
        content="Grafana running on port 3000",
        subject="grafana",
        anchor_files=["stacks/monitoring/compose.yaml"],
    )

    payload = {
        "repository": {"name": "infrastructure"},
        "commits": [
            {
                "id": "commit7890",
                "modified": ["stacks/monitoring/compose.yaml"],
                "added": [],
                "removed": [],
            }
        ],
        "after": "commit7890",
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), msg=raw_bytes, digestmod=hashlib.sha256).hexdigest()

    with TestClient(app) as client:
        res = client.post(
            "/webhook/git",
            content=raw_bytes,
            headers={"X-Forgejo-Signature": sig, "X-Forgejo-Event": "push"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["memories_flagged_stale"] == 1

    # Verify memory is flagged stale when recalled
    recalled = recall_memories(scope="infrastructure", query="Grafana")
    assert "[STALE: stacks/monitoring/compose.yaml modified in commit commit7]" in recalled


def test_webhook_ignores_non_push():
    with TestClient(app) as client:
        res = client.post(
            "/webhook/git",
            json={"action": "created"},
            headers={"X-GitHub-Event": "issue_comment"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ignored"


# --- 5. HTTP Export Endpoints ---

def test_export_http_endpoints():
    save_memory(scope="infrastructure", category="rule", content="Pin all docker container versions")

    with TestClient(app) as client:
        # Test /export/markdown
        res_md = client.get("/export/markdown")
        assert res_md.status_code == 200
        exports = res_md.json()["exports"]
        assert any(e["scope"] == "infrastructure" for e in exports)

        # Test /export/bundle download
        res_bundle = client.get("/export/bundle")
        assert res_bundle.status_code == 200
        assert res_bundle.headers["content-type"] == "application/gzip"
        assert len(res_bundle.content) > 0

        # Verify downloaded stream is a valid tar.gz containing memory.db
        with tarfile.open(fileobj=BytesIO(res_bundle.content), mode="r:gz") as tar:
            names = tar.getnames()
            assert "memory.db" in names
            assert any(n.startswith("exports") for n in names)


# --- 6. Transport Security & Reverse Proxy Compatibility ---

def test_transport_security_allows_reverse_proxy_domain():
    import anyio
    from starlette.requests import Request
    from mcp.server.sse import SseServerTransport
    from src.server import mcp

    t = SseServerTransport("/messages", security_settings=mcp.settings.transport_security)
    req = Request({"type": "http", "method": "GET", "headers": [(b"host", b"helios.example.com")]})
    res = anyio.run(t._security.validate_request, req, False)
    assert res is None


def test_hybrid_mcp_endpoints():
    with TestClient(app) as client:
        # 1. Test Streamable HTTP POST /sse (Antigravity IDE connection)
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        res_sse_post = client.post(
            "/sse",
            json=init_payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert res_sse_post.status_code == 200
        session_id = res_sse_post.headers.get("mcp-session-id")
        assert session_id is not None

        # 2. Test Streamable HTTP POST /mcp
        res_mcp_post = client.post(
            "/mcp",
            json=init_payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert res_mcp_post.status_code == 200


def test_hybrid_mcp_stale_session_fallback():
    import anyio
    from src.server import hybrid_handler

    # When a client sends a GET request with an expired/stale mcp-session-id,
    # it must fall back to standard SSE (sse_app) rather than returning 404 Session Not Found.
    messages_sent = []

    async def fake_send(message):
        messages_sent.append(message)

    async def fake_receive():
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/sse",
        "headers": [(b"mcp-session-id", b"stale_session_12345")],
    }
    anyio.run(hybrid_handler, scope, fake_receive, fake_send)
    assert any(m.get("type") == "http.response.start" and m.get("status") == 200 for m in messages_sent)


# --- 7. Scope Rename, Revalidation, Filtering & Pydantic Schema Inspection ---

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


def test_revalidate_memories_tool_and_markdown_sync():
    # Save memory with anchor_file
    save_res = save_memory(
        scope="service-a",
        category="fact",
        content="Service A binds to 0.0.0.0:4000",
        subject="host-port",
        anchor_files=["docker-compose.yml"],
    )
    # Extract memory ID from string e.g. "Memory #1 created..."
    import re
    m_id = int(re.search(r"#(\d+)", save_res).group(1))

    # Flag as stale via TestClient webhook
    with TestClient(app) as client:
        hook_payload = {
            "repository": {"name": "service-a"},
            "commits": [{"modified": ["docker-compose.yml"]}],
            "after": "deadbeef123",
        }
        res = client.post("/webhook/git", json=hook_payload)
        assert res.status_code == 200
        assert res.json()["memories_flagged_stale"] == 1

    # Verify memory is stale in recall and export
    recalled = recall_memories(scope="service-a", status_filter="stale")
    assert "[STALE:" in recalled

    export_file = get_export_dir() / "service-a.md"
    assert "[STALE:" in export_file.read_text(encoding="utf-8")

    # Revalidate using tool
    tool_res = revalidate_memories(memory_ids=[m_id])
    assert f"Revalidated 1 memories: #{m_id}" in tool_res

    # Check export was automatically synced and no longer has STALE
    assert "[STALE:" not in export_file.read_text(encoding="utf-8")
    recalled_active = recall_memories(scope="service-a", status_filter="active")
    assert "[STALE:" not in recalled_active
    assert "0.0.0.0:4000" in recalled_active


def test_recall_memories_category_and_status_filter_tools():
    save_memory(scope="shop", category="rule", content="Always use Decimal for currency", subject="money-rule")
    save_memory(scope="shop", category="fact", content="Checkout service on port 5005", subject="checkout-port")

    # Filter by category="rule"
    rule_res = recall_memories(scope="shop", category="rule")
    assert "Decimal for currency" in rule_res
    assert "Checkout service" not in rule_res

    # Filter by category="fact"
    fact_res = recall_memories(scope="shop", category="fact")
    assert "Checkout service" in fact_res
    assert "Decimal for currency" not in fact_res

    # Filter by status="stale" when none are stale
    stale_res = recall_memories(scope="shop", status_filter="stale")
    assert "No active memories found" in stale_res


def test_fastmcp_tool_schema_descriptions():
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    tool_map = {t.name: t for t in tools}

    # Verify all expected tools are registered
    expected_tools = {
        "recall_memories",
        "save_memory",
        "deprecate_memory",
        "recall_history",
        "revalidate_memories",
        "manage_scope_alias",
        "export_bundle",
        "manage_git_webhooks",
        "get_client_setup_bundle",
        "manage_server_config",
    }
    assert expected_tools.issubset(set(tool_map.keys()))

    # Inspect manage_server_config schema
    cfg_tool = tool_map["manage_server_config"]
    cfg_props = cfg_tool.inputSchema.get("properties", {})
    assert "action" in cfg_props
    assert "key" in cfg_props
    assert "value" in cfg_props

    # Inspect manage_git_webhooks schema
    gw_tool = tool_map["manage_git_webhooks"]
    gw_props = gw_tool.inputSchema.get("properties", {})
    assert "action" in gw_props
    assert "repos" in gw_props
    assert "include_forks" in gw_props

    # Inspect get_client_setup_bundle schema
    setup_tool = tool_map["get_client_setup_bundle"]
    setup_props = setup_tool.inputSchema.get("properties", {})
    assert "client" in setup_props
    assert "os_platform" in setup_props
    assert "instance_role" in setup_props
    assert "action" in setup_props

    # Inspect save_memory's schema
    save_tool = tool_map["save_memory"]
    schema = save_tool.inputSchema
    properties = schema.get("properties", {})

    # content description MUST contain 25-word limit notice
    content_prop = properties.get("content", {})
    assert "STRICT LIMIT: MUST be <= 25 words" in content_prop.get("description", "")

    # category description and enum
    cat_prop = properties.get("category", {})
    assert set(cat_prop.get("enum", [])) == {"rule", "fact", "preference", "episodic"}
    assert "guardrails" in cat_prop.get("description", "")

    # scope description
    scope_prop = properties.get("scope", {})
    assert "homelab" in scope_prop.get("description", "")

    # anchor_files description
    anchors_prop = properties.get("anchor_files", {})
    assert "docker-compose.yml" in anchors_prop.get("description", "")

    # replaces_id description
    replaces_prop = properties.get("replaces_id", {})
    assert "supersede" in replaces_prop.get("description", "")

    # Inspect recall_memories schema
    recall_tool = tool_map["recall_memories"]
    recall_props = recall_tool.inputSchema.get("properties", {})
    assert "category" in recall_props
    assert "status_filter" in recall_props
    assert "drift status" in recall_props["status_filter"].get("description", "")

    # Inspect revalidate_memories schema
    reval_tool = tool_map["revalidate_memories"]
    reval_props = reval_tool.inputSchema.get("properties", {})
    assert "memory_ids" in reval_props
    assert "stale memory IDs" in reval_props["memory_ids"].get("description", "")


# --- 8. Day-2 Live Configuration Management & Scope Statistics ---

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


def test_recall_memories_empty_category_normalization():
    save_memory(scope="shop", category="fact", content="Cart runs on port 4000", subject="cart-port")
    # Passing empty string category should not trigger Pydantic validation error and should return fact
    res = recall_memories(scope="shop", category="")
    assert "Cart runs on port 4000" in res


def test_recall_memories_stale_filter_does_not_bump_hit_count():
    from src.db import get_connection
    save_memory(scope="audit-test", category="fact", content="Temporary facts on 8080", subject="tmp", anchor_files=["file.txt"])
    
    with TestClient(app) as client:
        client.post("/webhook/git", json={"repository": {"name": "audit-test"}, "commits": [{"modified": ["file.txt"]}]})

    with get_connection() as conn:
        row = conn.execute("SELECT hit_count FROM memories WHERE scope = 'audit-test'").fetchone()
        assert row["hit_count"] == 0

    # Recall with status_filter="stale" should NOT increment hit count
    stale_res = recall_memories(scope="audit-test", status_filter="stale")
    assert "Temporary facts on 8080" in stale_res

    with get_connection() as conn:
        row = conn.execute("SELECT hit_count FROM memories WHERE scope = 'audit-test'").fetchone()
        assert row["hit_count"] == 0

    # Normal recall should increment hit count
    act_res = recall_memories(scope="audit-test", status_filter="all")
    assert "Temporary facts on 8080" in act_res

    with get_connection() as conn:
        row = conn.execute("SELECT hit_count FROM memories WHERE scope = 'audit-test'").fetchone()
        assert row["hit_count"] == 1


def test_git_webhook_payload_size_limit():
    with TestClient(app) as client:
        # 2 MB body exceeds 1 MB limit -> 413
        huge_body = b"A" * (2 * 1024 * 1024)
        res = client.post("/webhook/git", content=huge_body, headers={"content-type": "application/json"})
        assert res.status_code == 413
        assert "Payload exceeds 1MB limit" in res.text


@pytest.mark.anyio
async def test_fastmcp_async_call_thread_offloading():
    save_memory(scope="global", category="rule", content="Always offload sync tools to worker thread")
    res = await mcp.call_tool("recall_memories", {"scope": "global", "query": "offload"})
    assert res is not None
    # Output contains the rule
    content_text = res[0][0].text
    assert "Always offload sync tools" in content_text
