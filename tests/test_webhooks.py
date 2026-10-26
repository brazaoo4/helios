import pytest
import httpx
from unittest.mock import MagicMock, patch

from src.db import init_db, set_alias, upsert_memory
from src.server import manage_git_webhooks
from src.webhooks import (
    disable_repo_webhooks,
    enable_repo_webhooks,
    fetch_candidate_repositories,
    find_helios_hook,
    get_headers,
    list_repo_webhooks,
    match_helios_scope,
    normalize_api_url,
)


@pytest.fixture(autouse=True)
def setup_webhook_test_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HELIOS_GIT_PROVIDER", raising=False)
    monkeypatch.delenv("HELIOS_GIT_API_URL", raising=False)
    monkeypatch.delenv("HELIOS_GIT_TOKEN", raising=False)
    monkeypatch.delenv("HELIOS_GIT_OWNER", raising=False)
    monkeypatch.delenv("HELIOS_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("HELIOS_WEBHOOK_SECRET", raising=False)
    init_db()


def test_normalize_api_url():
    # GitHub
    assert normalize_api_url("github", None) == "https://api.github.com"
    assert normalize_api_url("github", "") == "https://api.github.com"
    assert normalize_api_url("github", "https://api.github.com/") == "https://api.github.com"

    # GitLab
    assert normalize_api_url("gitlab", None) == "https://gitlab.com/api/v4"
    assert normalize_api_url("gitlab", "https://gitlab.example.com") == "https://gitlab.example.com/api/v4"
    assert normalize_api_url("gitlab", "https://gitlab.example.com/api/v4/") == "https://gitlab.example.com/api/v4"

    # Forgejo / Gitea
    assert normalize_api_url("forgejo", "https://git.example.com") == "https://git.example.com/api/v1"
    assert normalize_api_url("gitea", "https://git.example.com/api/v1/") == "https://git.example.com/api/v1"

    with pytest.raises(ValueError, match="API URL is required"):
        normalize_api_url("forgejo", "")


def test_get_headers():
    gh = get_headers("github", "tok-gh")
    assert gh["Authorization"] == "Bearer tok-gh"
    assert "application/vnd.github+json" in gh["Accept"]

    gl = get_headers("gitlab", "tok-gl")
    assert gl["PRIVATE-TOKEN"] == "tok-gl"

    fj = get_headers("forgejo", "tok-fj")
    assert fj["Authorization"] == "token tok-fj"


def test_candidate_repositories_filtering():
    raw_repos = [
        # 1. Owned, normal repo -> included
        {"name": "helios", "full_name": "braz/helios", "owner": {"login": "braz"}, "fork": False, "archived": False},
        # 2. Owned fork -> excluded unless include_forks=True
        {"name": "forked-lib", "full_name": "braz/forked-lib", "owner": {"login": "braz"}, "fork": True, "archived": False},
        # 3. Owned archived -> excluded
        {"name": "old-tool", "full_name": "braz/old-tool", "owner": {"login": "braz"}, "fork": False, "archived": True},
        # 4. Collaborator on someone else's repo -> excluded
        {"name": "external-project", "full_name": "other-user/external-project", "owner": {"login": "other-user"}, "fork": False, "archived": False},
    ]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=raw_repos)

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))

    # Without include_forks (default)
    filtered = fetch_candidate_repositories(client, "github", "https://api.github.com", "braz", include_forks=False)
    assert len(filtered) == 1
    assert filtered[0]["name"] == "helios"

    # With include_forks=True
    with_forks = fetch_candidate_repositories(client, "github", "https://api.github.com", "braz", include_forks=True)
    assert len(with_forks) == 2
    names = {r["name"] for r in with_forks}
    assert names == {"helios", "forked-lib"}


def test_match_helios_scope():
    upsert_memory("ticketera", "fact", "Port 8080", subject="app-port")
    set_alias("legacy-tickets", "ticketera")

    from src.webhooks import get_known_helios_scopes
    known = get_known_helios_scopes()

    assert match_helios_scope("ticketera", "braz/ticketera", known) == "ticketera"
    assert match_helios_scope("legacy-tickets", "braz/legacy-tickets", known) == "ticketera"
    assert match_helios_scope("unknown-repo", "braz/unknown-repo", known) is None


def test_list_enable_disable_webhooks_flow():
    target_webhook = "https://helios.example.com/webhook/git"

    # Mock responses for GitHub
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        # 1. User
        if url_str == "https://api.github.com/user":
            return httpx.Response(200, json={"login": "braz"})
        # 2. List repos
        if "/user/repos" in url_str:
            return httpx.Response(200, json=[
                {"name": "helios", "full_name": "braz/helios", "owner": {"login": "braz"}, "fork": False, "archived": False, "id": 101},
                {"name": "service-b", "full_name": "braz/service-b", "owner": {"login": "braz"}, "fork": False, "archived": False, "id": 102},
            ])
        # 3. Hooks for helios (already enabled)
        if "/repos/braz/helios/hooks" in url_str and request.method == "GET":
            return httpx.Response(200, json=[
                {"id": 999, "config": {"url": target_webhook}}
            ])
        # 4. Hooks for service-b (not enabled)
        if "/repos/braz/service-b/hooks" in url_str and request.method == "GET":
            return httpx.Response(200, json=[])
        # 5. Create hook on service-b
        if "/repos/braz/service-b/hooks" in url_str and request.method == "POST":
            return httpx.Response(201, json={"id": 1000, "config": {"url": target_webhook}})
        # 6. Delete hook on helios
        if "/repos/braz/helios/hooks/999" in url_str and request.method == "DELETE":
            return httpx.Response(204)

        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(mock_handler)
    orig_client = httpx.Client

    def custom_client(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    with patch("httpx.Client", side_effect=custom_client):
        # 1. List
        repos = list_repo_webhooks(
            provider="github",
            token="gh-test-tok",
            owner="braz",
            webhook_url=target_webhook,
        )
        assert len(repos) == 2
        helios_info = next(r for r in repos if r["name"] == "helios")
        service_b_info = next(r for r in repos if r["name"] == "service-b")

        assert helios_info["enabled"] is True
        assert helios_info["hook_id"] == 999
        assert service_b_info["enabled"] is False
        assert service_b_info["hook_id"] is None

        # 2. Enable service-b
        en_res = enable_repo_webhooks(
            repos=["braz/service-b"],
            provider="github",
            token="gh-test-tok",
            webhook_url=target_webhook,
            webhook_secret="hmac-secret",
        )
        assert "braz/service-b" in en_res["enabled"]

        # 3. Enable helios (already enabled)
        en_helios = enable_repo_webhooks(
            repos=["braz/helios"],
            provider="github",
            token="gh-test-tok",
            webhook_url=target_webhook,
        )
        assert "braz/helios" in en_helios["already_enabled"]

        # 4. Disable helios
        dis_res = disable_repo_webhooks(
            repos=["braz/helios"],
            provider="github",
            token="gh-test-tok",
            webhook_url=target_webhook,
        )
        assert "braz/helios" in dis_res["disabled"]


def test_manage_git_webhooks_unconfigured_fallback():
    # When HELIOS_GIT_TOKEN or HELIOS_WEBHOOK_URL is not set
    res = manage_git_webhooks(action="list")
    assert "Git webhook management is not configured on this server" in res
    assert "HELIOS_GIT_TOKEN" in res
    assert "Manual Configuration" in res
    assert "Conversational Automation" in res


def test_manage_git_webhooks_mcp_tool_actions(monkeypatch):
    monkeypatch.setenv("HELIOS_GIT_PROVIDER", "forgejo")
    monkeypatch.setenv("HELIOS_GIT_API_URL", "https://git.example.com")
    monkeypatch.setenv("HELIOS_GIT_TOKEN", "fj-token-123")
    monkeypatch.setenv("HELIOS_WEBHOOK_URL", "https://helios.example.com/webhook/git")

    # Mock list_repo_webhooks
    mock_candidates = [
        {"repo": "braz/helios", "name": "helios", "owner": "braz", "enabled": True, "hook_id": 1, "is_fork": False, "is_archived": False, "matched_scope": "helios"},
        {"repo": "braz/ticketera", "name": "ticketera", "owner": "braz", "enabled": False, "hook_id": None, "is_fork": False, "is_archived": False, "matched_scope": "ticketera"},
    ]

    with patch("src.server.list_repo_webhooks", return_value=mock_candidates), \
         patch("src.server.enable_repo_webhooks", return_value={"enabled": ["braz/ticketera"], "already_enabled": [], "failed": []}), \
         patch("src.server.disable_repo_webhooks", return_value={"disabled": ["braz/helios"], "not_found": [], "failed": []}):

        # 1. Action: list
        list_out = manage_git_webhooks(action="list")
        assert "- [x] `braz/helios`" in list_out
        assert "- [ ] `braz/ticketera`" in list_out
        assert "Agent Instruction" in list_out

        # 2. Action: enable without repos -> error
        assert "Error:" in manage_git_webhooks(action="enable")

        # 3. Action: enable with repos
        en_out = manage_git_webhooks(action="enable", repos=["braz/ticketera"])
        assert "Successfully enabled drift webhooks on: `braz/ticketera`" in en_out

        # 4. Action: disable with repos
        dis_out = manage_git_webhooks(action="disable", repos=["braz/helios"])
        assert "Successfully disabled drift webhooks on: `braz/helios`" in dis_out


def test_cross_source_token_exfiltration_prevented(monkeypatch):
    from src.db import set_runtime_setting
    from src.webhooks import _verify_token_destination_allowed

    # Env provides GIT token
    monkeypatch.setenv("HELIOS_GIT_TOKEN", "super-secret-production-pat")
    monkeypatch.setenv("HELIOS_GIT_API_URL", "https://git.internal.lan")

    # If target matches env origin, it is allowed (returns None without raising)
    _verify_token_destination_allowed("https://git.internal.lan")

    # But if someone overrides HELIOS_GIT_API_URL in SQLite to an external attacker endpoint:
    set_runtime_setting("HELIOS_GIT_API_URL", "https://attacker.com/api")

    with pytest.raises(ValueError, match="Security violation: HELIOS_GIT_TOKEN is configured in environment"):
        _verify_token_destination_allowed("https://attacker.com/api")


def test_enable_repo_webhooks_single_name_fallback_and_url_encoding(monkeypatch):
    from src.webhooks import enable_repo_webhooks

    monkeypatch.setenv("HELIOS_GIT_PROVIDER", "forgejo")
    monkeypatch.setenv("HELIOS_GIT_API_URL", "https://git.internal.lan")
    monkeypatch.setenv("HELIOS_GIT_TOKEN", "fj-token-xyz")
    monkeypatch.setenv("HELIOS_GIT_OWNER", "braz")
    monkeypatch.setenv("HELIOS_WEBHOOK_URL", "https://helios.example.com/webhook/git")

    called_urls = []

    def mock_get(self, url, **kwargs):
        called_urls.append(url)
        class MockResp:
            status_code = 200
            text = "[]"
            def json(self):
                return []
        return MockResp()

    def mock_post(self, url, **kwargs):
        called_urls.append(url)
        class MockResp:
            status_code = 201
            text = '{"id": 42}'
            def json(self):
                return {"id": 42}
        return MockResp()

    with patch("httpx.Client.get", new=mock_get), patch("httpx.Client.post", new=mock_post):
        # Pass a single-name repo with special characters (e.g. "my repo+v1")
        res = enable_repo_webhooks(repos=["my repo+v1"])
        assert "my repo+v1" in res["enabled"]
        # Ensure owner "braz" was prepended and repo name was URL-encoded in the API path
        assert any("/repos/braz/my%20repo%2Bv1/hooks" in u for u in called_urls)
