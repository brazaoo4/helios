from unittest.mock import patch

import httpx
import pytest

from src.db import set_alias, upsert_memory
from src.server import manage_git_webhooks
from src.webhooks import (
    disable_repo_webhooks,
    enable_repo_webhooks,
    fetch_candidate_repositories,
    get_headers,
    list_repo_webhooks,
    match_helios_scope,
    normalize_api_url,
)


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


def test_webhooks_gitlab_and_disable_lifecycle(monkeypatch):
    from src.webhooks import (
        _get_authenticated_user,
        disable_repo_webhooks,
        enable_repo_webhooks,
        fetch_candidate_repositories,
    )

    monkeypatch.setenv("HELIOS_GIT_PROVIDER", "gitlab")
    monkeypatch.setenv("HELIOS_GIT_API_URL", "https://gitlab.example.com")
    monkeypatch.setenv("HELIOS_GIT_TOKEN", "gl-token-123")
    monkeypatch.setenv("HELIOS_WEBHOOK_URL", "https://helios.example.com/webhook/git")

    # 1. Validation checks when params missing
    with pytest.raises(ValueError, match="No repositories specified"):
        enable_repo_webhooks(repos=[])
    with pytest.raises(ValueError, match="No repositories specified"):
        disable_repo_webhooks(repos=[])

    # 2. _get_authenticated_user test
    class MockUserResp:
        status_code = 200
        def json(self):
            return {"username": "gitlab-user"}

    with patch("httpx.Client.get", return_value=MockUserResp()):
        with httpx.Client() as client:
            user = _get_authenticated_user(client, "gitlab", "https://gitlab.example.com/api/v4")
            assert user == "gitlab-user"

    # 3. fetch_candidate_repositories with GitLab
    class MockProjectsResp:
        status_code = 200
        def json(self):
            return [
                {
                    "name": "my-project",
                    "path_with_namespace": "my-group/my-project",
                    "namespace": {"path": "my-group"},
                    "forked_from_project": None,
                    "archived": False,
                    "id": 101,
                }
            ]

    with httpx.Client() as client:
        with patch.object(client, "get", return_value=MockProjectsResp()):
            repos = fetch_candidate_repositories(
                client,
                provider="gitlab",
                api_url="https://gitlab.example.com/api/v4",
                target_owner="my-group",
            )
            assert len(repos) == 1
            assert repos[0]["full_name"] == "my-group/my-project"

    # 4. enable_repo_webhooks and disable_repo_webhooks on GitLab
    class MockHooksList:
        status_code = 200
        def json(self):
            return [{"id": 55, "url": "https://helios.example.com/webhook/git"}]

    class MockDeleteResp:
        status_code = 204
        text = ""

    with patch("httpx.Client.get", return_value=MockHooksList()):
        # Already enabled
        res_already = enable_repo_webhooks(repos=["my-group/my-project"])
        assert "my-group/my-project" in res_already["already_enabled"]

        # Disable
        with patch("httpx.Client.delete", return_value=MockDeleteResp()):
            res_dis = disable_repo_webhooks(repos=["my-group/my-project"])
            assert "my-group/my-project" in res_dis["disabled"]


def test_outbound_ssrf_and_token_destination_pinning(monkeypatch):
    import socket

    from src.db import set_runtime_setting
    from src.webhooks import _assert_safe_outbound_url, _verify_token_destination_allowed

    # 1. Blocked resolved IPs (loopback, IPv4-mapped IPv6 loopback, cloud metadata)
    for bad_ip in ("127.0.0.1", "::ffff:127.0.0.1", "169.254.169.254", "100.100.100.200"):
        with patch(
            "src.webhooks.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (bad_ip, 443))],
        ):
            with pytest.raises(ValueError, match="forbidden"):
                _assert_safe_outbound_url("https://evil-redirect.test")

    # 2. Fail-closed on DNS resolution failure
    with patch("src.webhooks.socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")):
        with pytest.raises(ValueError, match="Unable to resolve destination host"):
            _assert_safe_outbound_url("https://nonexistent.invalid")

    # 3. Refuse to send env-sourced HELIOS_GIT_TOKEN to a DB-overridden Git host
    monkeypatch.setenv("HELIOS_GIT_PROVIDER", "forgejo")
    monkeypatch.setenv("HELIOS_GIT_API_URL", "https://git.internal.lan")
    monkeypatch.setenv("HELIOS_GIT_TOKEN", "env-pat-123")
    set_runtime_setting("HELIOS_GIT_API_URL", "https://attacker.example.com")
    with pytest.raises(ValueError, match="Security violation"):
        _verify_token_destination_allowed("https://attacker.example.com/api/v1")

    # Matching host stays allowed
    _verify_token_destination_allowed("https://git.internal.lan/api/v1")


def test_webhook_provider_fallbacks_pagination_and_error_redaction(monkeypatch):
    from src.webhooks import fetch_commit_diff

    monkeypatch.setenv("HELIOS_GIT_PROVIDER", "github")
    monkeypatch.setenv("HELIOS_GIT_TOKEN", "ghp_" + ("x" * 36))
    monkeypatch.setenv("HELIOS_GIT_OWNER", "acme-org")
    monkeypatch.setenv("HELIOS_WEBHOOK_URL", "https://helios.example.com/webhook/git")

    # 1. /user/repos returns 403 -> fallback to /orgs/acme-org/repos + 2-page pagination
    page1 = [
        {"name": f"repo-{i}", "full_name": f"acme-org/repo-{i}", "owner": {"login": "acme-org"}, "fork": False, "archived": False, "id": i}
        for i in range(100)
    ]
    page2 = [
        {"name": "repo-100", "full_name": "acme-org/repo-100", "owner": {"login": "acme-org"}, "fork": False, "archived": False, "id": 100}
    ]

    def gh_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/user/repos" in url:
            return httpx.Response(403, text="forbidden")
        if "/orgs/acme-org/repos" in url:
            page = request.url.params.get("page")
            return httpx.Response(200, json=page1 if page == "1" else page2)
        if "/repos/acme-org/repo-0/hooks" in url and request.method == "GET":
            return httpx.Response(500, text="error for ghp_" + ("x" * 36))
        if "/repos/acme-org/repo-1/hooks" in url and request.method == "POST":
            return httpx.Response(500, text="create failed")
        if "/repos/acme-org/repo-1/hooks" in url and request.method == "GET":
            return httpx.Response(200, json=[])
        if "/repos/acme-org/missing/hooks" in url and request.method == "GET":
            return httpx.Response(200, json=[])
        if "/repos/acme-org/del-err/hooks" in url and request.method == "GET":
            return httpx.Response(200, json=[{"id": 9, "config": {"url": "https://helios.example.com/webhook/git"}}])
        if "/repos/acme-org/del-err/hooks/9" in url and request.method == "DELETE":
            return httpx.Response(500, text="delete failed")
        return httpx.Response(404)

    transport = httpx.MockTransport(gh_handler)
    orig_client = httpx.Client

    with patch("httpx.Client", side_effect=lambda *a, **kw: orig_client(*a, **{**kw, "transport": transport})):
        with httpx.Client(transport=transport) as c:
            repos = fetch_candidate_repositories(c, "github", "https://api.github.com", "acme-org")
        assert len(repos) == 101

        en_res = enable_repo_webhooks(repos=["acme-org/repo-0", "acme-org/repo-1"])
        assert len(en_res["failed"]) == 2
        assert ("ghp_" + ("x" * 36)) not in en_res["failed"][0]["error"]

        dis_res = disable_repo_webhooks(repos=["acme-org/missing", "acme-org/del-err"])
        assert dis_res["not_found"] == ["acme-org/missing"]
        assert len(dis_res["failed"]) == 1

    # 2. fetch_commit_diff edge cases: unconfigured/non-list GitLab JSON/short repo lookup
    assert fetch_commit_diff("braz/helios", "0" * 40) is None
    assert fetch_commit_diff("helios", "abc123", provider="forgejo", api_url="") is None

    def bad_gl(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/user"):
            return httpx.Response(200, json={"username": "gl-owner"})
        return httpx.Response(200, json={"unexpected": "dict-not-list"})

    gl_transport = httpx.MockTransport(bad_gl)
    monkeypatch.delenv("HELIOS_GIT_OWNER", raising=False)
    monkeypatch.setenv("HELIOS_GIT_API_URL", "https://gitlab.example.com")
    with patch("httpx.Client", side_effect=lambda *a, **kw: orig_client(*a, **{**kw, "transport": gl_transport})):
        assert (
            fetch_commit_diff(
                "my-repo",
                "abc123",
                provider="gitlab",
                api_url="https://gitlab.example.com",
            )
            is None
        )

    # 3. GitLab group & Forgejo org repo listing fallback when /projects or /user/repos fails
    def group_org_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/api/v4/projects" in url or "/api/v1/user/repos" in url:
            return httpx.Response(404, text="not found")
        if "/api/v4/groups/my-grp/projects" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "gl-app",
                        "path_with_namespace": "my-grp/gl-app",
                        "namespace": {"path": "my-grp"},
                        "archived": False,
                    }
                ],
            )
        if "/api/v1/orgs/my-org/repos" in url:
            return httpx.Response(
                200,
                json=[
                    {"name": "fj-app", "full_name": "my-org/fj-app", "owner": {"login": "my-org"}}
                ],
            )
        return httpx.Response(404)

    go_transport = httpx.MockTransport(group_org_handler)
    with httpx.Client(transport=go_transport) as c:
        gl_repos = fetch_candidate_repositories(c, "gitlab", "https://gitlab.example.com/api/v4", "my-grp")
        fj_repos = fetch_candidate_repositories(c, "forgejo", "https://git.internal.lan/api/v1", "my-org")
    assert [r["full_name"] for r in gl_repos] == ["my-grp/gl-app"]
    assert [r["full_name"] for r in fj_repos] == ["my-org/fj-app"]

    # 4. Validation & provider error paths (bad repo ident, missing webhook url, 404 diff)
    from src.webhooks import _filter_diff_for_files, _validate_repo_ident

    with pytest.raises(ValueError, match="Invalid repository owner"):
        _validate_repo_ident("..", "repo")
    with pytest.raises(ValueError, match="Invalid repository name"):
        _validate_repo_ident("owner", "bad/name")

    monkeypatch.delenv("HELIOS_WEBHOOK_URL", raising=False)
    with pytest.raises(ValueError, match="HELIOS_WEBHOOK_URL is required"):
        enable_repo_webhooks(repos=["acme-org/repo-0"])
    with pytest.raises(ValueError, match="HELIOS_WEBHOOK_URL is required"):
        disable_repo_webhooks(repos=["acme-org/repo-0"])

    # Empty matched_files or no diff header truncates cleanly
    assert _filter_diff_for_files("plain diff text", None) == "plain diff text"

    not_found_transport = httpx.MockTransport(lambda req: httpx.Response(404, text="missing"))
    with patch(
        "httpx.Client",
        side_effect=lambda *a, **kw: orig_client(*a, **{**kw, "transport": not_found_transport}),
    ):
        assert fetch_commit_diff("acme/app", "abc123", provider="github") is None
        assert fetch_commit_diff("acme/app", "abc123", provider="forgejo", api_url="https://git.internal.lan") is None

