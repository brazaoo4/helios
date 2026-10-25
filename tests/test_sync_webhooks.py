import pytest
import httpx
from unittest.mock import MagicMock, patch

from scripts.sync_webhooks import (
    create_webhook,
    get_headers,
    list_repositories,
    list_webhooks,
    main,
    normalize_api_url,
    sync_webhooks,
    webhook_already_exists,
)


def test_normalize_api_url():
    # GitHub defaults
    assert normalize_api_url("github", "") == "https://api.github.com"
    assert normalize_api_url("github", None) == "https://api.github.com"
    assert normalize_api_url("github", "https://api.github.com/") == "https://api.github.com"

    # Forgejo / Gitea normalization
    assert normalize_api_url("forgejo", "https://git.example.com") == "https://git.example.com/api/v1"
    assert normalize_api_url("forgejo", "https://git.example.com/") == "https://git.example.com/api/v1"
    assert normalize_api_url("gitea", "https://git.example.com/api/v1") == "https://git.example.com/api/v1"

    with pytest.raises(ValueError, match="--api-url is required"):
        normalize_api_url("forgejo", "")


def test_get_headers():
    gh_headers = get_headers("github", "secret-gh-tok")
    assert gh_headers["Authorization"] == "Bearer secret-gh-tok"
    assert "application/vnd.github+json" in gh_headers["Accept"]

    forgejo_headers = get_headers("forgejo", "secret-fj-tok")
    assert forgejo_headers["Authorization"] == "token secret-fj-tok"


def test_webhook_already_exists():
    target = "https://helios.example.com/webhook/git"
    existing_hooks = [
        {"id": 1, "config": {"url": "https://other.com/hook"}},
        {"id": 2, "config": {"url": "https://helios.example.com/webhook/git/"}},
    ]
    assert webhook_already_exists(existing_hooks, target) is True

    non_matching_hooks = [
        {"id": 1, "config": {"url": "https://other.com/hook"}},
    ]
    assert webhook_already_exists(non_matching_hooks, target) is False


def test_sync_webhooks_flow():
    target_url = "https://helios.example.com/webhook/git"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)

        # 1. List repos
        if "/orgs/my-org/repos" in url_str:
            return httpx.Response(
                200,
                json=[
                    {"name": "repo-1", "full_name": "my-org/repo-1", "owner": {"login": "my-org"}},
                    {"name": "repo-2", "full_name": "my-org/repo-2", "owner": {"login": "my-org"}},
                ],
            )

        # 2. List webhooks
        if "/repos/my-org/repo-1/hooks" in url_str and request.method == "GET":
            # repo-1 already has the webhook
            return httpx.Response(
                200,
                json=[{"id": 10, "config": {"url": target_url}}],
            )

        if "/repos/my-org/repo-2/hooks" in url_str and request.method == "GET":
            # repo-2 has no webhooks
            return httpx.Response(200, json=[])

        # 3. Create webhook
        if "/repos/my-org/repo-2/hooks" in url_str and request.method == "POST":
            return httpx.Response(201, json={"id": 11, "status": "created"})

        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(mock_handler)

    # Patch httpx.Client to use mock transport
    orig_client = httpx.Client

    def custom_client(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    with patch("httpx.Client", side_effect=custom_client):
        stats = sync_webhooks(
            provider="forgejo",
            api_url="https://git.example.com",
            token="test-token",
            webhook_url=target_url,
            webhook_secret="hmac-secret",
            owner="my-org",
        )

    assert stats["total_repos"] == 2
    assert stats["skipped"] == 1
    assert stats["registered"] == 1
    assert stats["errors"] == 0


def test_sync_webhooks_main_cli(monkeypatch):
    test_args = [
        "sync_webhooks.py",
        "--provider", "github",
        "--token", "gh-tok",
        "--webhook-url", "https://helios.example.com/webhook/git",
    ]
    monkeypatch.setattr("sys.argv", test_args)

    with patch("scripts.sync_webhooks.sync_webhooks") as mock_sync:
        mock_sync.return_value = {"total_repos": 1, "registered": 1, "skipped": 0, "errors": 0}
        main()
        mock_sync.assert_called_once()
        assert mock_sync.call_args[1]["provider"] == "github"
        assert mock_sync.call_args[1]["api_url"] == "https://api.github.com"
