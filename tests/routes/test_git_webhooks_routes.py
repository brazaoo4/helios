"""Tests for universal Git webhook ingress (/webhook/git and /webhook/forgejo)."""

import hashlib
import hmac
import json

from starlette.testclient import TestClient

from src.server import app, recall_memories, save_memory


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


def test_git_webhook_payload_size_limit():
    with TestClient(app) as client:
        # 2 MB body exceeds 1 MB limit -> 413
        huge_body = b"A" * (2 * 1024 * 1024)
        res = client.post("/webhook/git", content=huge_body, headers={"content-type": "application/json"})
        assert res.status_code == 413
        assert "Payload exceeds 1MB limit" in res.text


def test_webhook_signature_helpers():
    from src.routes.git_webhooks import verify_forgejo_signature, verify_github_signature

    body = b"hello world"
    secret = "secret"
    expected = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()

    # Forgejo
    assert not verify_forgejo_signature(body, "", secret)
    assert verify_forgejo_signature(body, f"sha256={expected}", secret)
    assert verify_forgejo_signature(body, expected, secret)

    # GitHub
    assert not verify_github_signature(body, "", secret)
    assert not verify_github_signature(body, "badprefix", secret)
    assert verify_github_signature(body, f"sha256={expected}", secret)


def test_webhook_gemini_diff_triage_keeps_unchanged_active_and_flags_contradicted(monkeypatch):
    from unittest.mock import patch

    import httpx

    monkeypatch.setenv("HELIOS_WEBHOOK_SECRET", "triage-hook-secret")
    monkeypatch.setenv("HELIOS_GIT_PROVIDER", "forgejo")
    monkeypatch.setenv("HELIOS_GIT_API_URL", "https://git.internal.lan")
    monkeypatch.setenv("HELIOS_GIT_TOKEN", "fake-git-pat")

    save_memory(
        scope="triage-app",
        category="fact",
        content="App listens on port 8000",
        subject="app-port",
        anchor_files=["compose.yaml"],
    )
    save_memory(
        scope="triage-app",
        category="fact",
        content="Database uses PostgreSQL 16",
        subject="db-ver",
        anchor_files=["compose.yaml"],
    )

    monkeypatch.setenv("HELIOS_GEMINI_API_KEY", "fake-gemini-key")
    sample_diff = "diff --git a/compose.yaml b/compose.yaml\n-      - 8000:8000\n+      - 8080:8000\n"

    def gemini_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "decisions": [
                                                {
                                                    "id": 1,
                                                    "status": "STALE",
                                                    "reason": "Port changed from 8000 to 8080",
                                                },
                                                {
                                                    "id": 2,
                                                    "status": "UNCHANGED",
                                                    "reason": "PostgreSQL image unchanged",
                                                },
                                            ]
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(gemini_handler)
    orig_client = httpx.Client

    def semantic_client(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    payload = {
        "repository": {"name": "braz/triage-app"},
        "commits": [{"id": "a1b2c3d4e5", "modified": ["compose.yaml"]}],
        "after": "a1b2c3d4e5",
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"triage-hook-secret", msg=raw_bytes, digestmod=hashlib.sha256).hexdigest()

    with (
        patch("src.webhooks.fetch_commit_diff", return_value=sample_diff),
        patch("src.semantic.httpx.Client", side_effect=semantic_client),
        TestClient(app) as client,
    ):
        res = client.post(
            "/webhook/git",
            content=raw_bytes,
            headers={"X-Forgejo-Signature": sig, "X-Forgejo-Event": "push"},
        )
        assert res.status_code == 200
        assert res.json()["memories_flagged_stale"] == 1

    from src.db import get_connection

    with get_connection() as conn:
        row1 = conn.execute("SELECT status, stale_reason FROM memories WHERE id = 1").fetchone()
        row2 = conn.execute(
            "SELECT status, last_verified_commit FROM memories WHERE id = 2"
        ).fetchone()
        assert row1["status"] == "stale"
        assert row1["stale_reason"] == "Port changed from 8000 to 8080 (a1b2c3d)"
        assert row2["status"] == "active"
        assert row2["last_verified_commit"] == "a1b2c3d"


def test_git_webhook_bearer_auth_malformed_inputs_and_gitlab_project_fallback(monkeypatch):
    monkeypatch.setenv("HELIOS_WEBHOOK_SECRET", "bearer-hook-secret")
    headers_bearer = {"Authorization": "Bearer bearer-hook-secret"}

    save_memory(
        scope="gl-proj",
        category="fact",
        content="App reads deploy.yml",
        subject="deploy",
        anchor_files=["deploy.yml"],
    )

    with TestClient(app) as client:
        # 1. Empty body, malformed JSON, empty dict, missing repository -> 400
        assert client.post("/webhook/git", content=b"   ", headers=headers_bearer).status_code == 400
        assert client.post("/webhook/git", content=b"{bad", headers=headers_bearer).status_code == 400
        assert client.post("/webhook/git", json={}, headers=headers_bearer).status_code == 400
        assert client.post("/webhook/git", json={"commits": []}, headers=headers_bearer).status_code == 400

        # 2. Payload object_kind != push ignored (200)
        res_mr = client.post(
            "/webhook/git",
            json={"object_kind": "merge_request", "project": {"name": "gl-proj"}},
            headers=headers_bearer,
        )
        assert res_mr.status_code == 200
        assert res_mr.json()["status"] == "ignored"

        # 3. GitLab project fallback + zeroed 'after' falls back to head_commit.id
        res_ok = client.post(
            "/webhook/git",
            json={
                "object_kind": "push",
                "project": {"name": "gl-proj"},
                "after": "0" * 40,
                "head_commit": {"id": "deadbeef1234"},
                "commits": ["skip-non-dict", {"id": "deadbeef1234", "modified": ["deploy.yml"]}],
            },
            headers=headers_bearer,
        )
        assert res_ok.status_code == 200
        body = res_ok.json()
        assert body["repository"] == "gl-proj"
        assert body["commits_evaluated"] == 2
        assert body["files_evaluated"] == 1
        assert body["memories_flagged_stale"] == 1

    from src.db import get_connection

    with get_connection() as conn:
        row = conn.execute("SELECT status, stale_reason FROM memories WHERE scope = 'gl-proj'").fetchone()
        assert row["status"] == "stale"
        assert "deadbee" in row["stale_reason"]

