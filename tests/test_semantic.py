"""Unit and integration tests for Gemini embeddings, RRF search, diff fetching, and contradiction auditing."""

import json
from unittest.mock import patch

import httpx
import pytest

from src.db import get_connection, query_memories, upsert_memory
from src.semantic import (
    EMBEDDING_DIMS,
    analyze_scope_contradictions,
    cosine_similarity,
    fetch_gemini_embedding,
    pack_embedding,
    reciprocal_rank_fusion,
    triage_webhook_drift_with_gemini,
    unpack_embedding,
)
from src.webhooks import fetch_commit_diff


def _basis_vec(index: int, secondary: int | None = None, weight: float = 0.0) -> list[float]:
    vec = [0.0] * EMBEDDING_DIMS
    vec[index] = 1.0
    if secondary is not None:
        vec[secondary] = weight
    return vec


def test_embedding_pack_unpack_and_cosine_similarity():
    v1 = _basis_vec(0, 1, 1.0)
    b1 = pack_embedding(v1)
    assert len(b1) == EMBEDDING_DIMS * 4
    u1 = unpack_embedding(b1)
    assert pytest.approx(cosine_similarity(u1, u1), abs=1e-5) == 1.0

    u2 = unpack_embedding(pack_embedding(_basis_vec(2)))
    assert pytest.approx(cosine_similarity(u1, u2), abs=1e-5) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test_hybrid_semantic_search_and_rrf(monkeypatch):
    # Disabled when key unset
    assert fetch_gemini_embedding("test query") is None

    monkeypatch.setenv("HELIOS_GEMINI_API_KEY", "fake-gemini-key")

    def fake_post(self, url, **kwargs):
        body = kwargs.get("json", {})
        text = body["content"]["parts"][0]["text"].lower()
        if "nginx" in text or "https" in text or "reverse proxy" in text:
            vals = _basis_vec(0)
        elif "postgres" in text:
            vals = _basis_vec(1)
        else:
            vals = _basis_vec(2)
        return httpx.Response(200, json={"embedding": {"values": vals}})

    with patch("httpx.Client.post", new=fake_post):
        m_proxy = upsert_memory(
            "mesh",
            "fact",
            "Nginx Proxy Manager terminates Let's Encrypt wildcard TLS",
            subject="ingress",
        )
        upsert_memory(
            "mesh",
            "fact",
            "PostgreSQL 16 runs on internal db network",
            subject="db",
        )

        with get_connection() as conn:
            emb_count = conn.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
            assert emb_count == 2

        # Query uses completely different phrasing ("HTTPS reverse proxy") with zero lexical overlap
        results = query_memories("mesh", "HTTPS reverse proxy")
        assert len(results) == 1
        assert results[0]["id"] == m_proxy["id"]

    # RRF merges lexical and semantic rankings cleanly
    row_a = {"id": 10, "status": "active", "category": "rule"}
    row_b = {"id": 20, "status": "active", "category": "fact"}
    row_c = {"id": 30, "status": "stale", "category": "episodic"}
    fused = reciprocal_rank_fusion([row_b, row_c], [row_a, row_b], limit=3)
    assert fused[0]["id"] == 20  # present in both lists -> highest RRF score


def test_gemini_error_fallbacks_and_contradictions_edge_cases(monkeypatch):
    with pytest.raises(ValueError, match="HELIOS_GEMINI_API_KEY"):
        analyze_scope_contradictions("demo", [])

    monkeypatch.setenv("HELIOS_GEMINI_API_KEY", "fake-gemini-key")
    assert analyze_scope_contradictions("demo", [{"id": 1, "scope": "demo", "category": "fact", "content": "Only one"}]) == {
        "contradictions": [],
        "merge_candidates": [],
    }

    with patch("httpx.Client.post", return_value=httpx.Response(500, text="Server error")):
        assert fetch_gemini_embedding("hello") is None
        assert triage_webhook_drift_with_gemini("diff", [{"id": 1, "content": "x"}], "abc") is None
        with pytest.raises(RuntimeError, match="HTTP 500"):
            analyze_scope_contradictions(
                "demo",
                [
                    {"id": 1, "scope": "demo", "category": "fact", "content": "One"},
                    {"id": 2, "scope": "demo", "category": "fact", "content": "Two"},
                ],
            )

    with patch("httpx.Client.post", side_effect=httpx.ConnectError("offline")):
        assert fetch_gemini_embedding("hello") is None
        assert triage_webhook_drift_with_gemini("diff", [{"id": 1, "content": "x"}], "abc") is None

    with patch("httpx.Client.post", return_value=httpx.Response(200, json={"embedding": {"values": [1.0]}})):
        assert fetch_gemini_embedding("bad-dim") is None
        assert fetch_gemini_embedding("   ") is None


def test_fetch_commit_diff_providers(monkeypatch):
    monkeypatch.setenv("HELIOS_GIT_TOKEN", "git-pat-123")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.github.com" in url:
            return httpx.Response(
                200,
                text=(
                    "diff --git a/README.md b/README.md\n+typo\n"
                    "diff --git a/compose.yaml b/compose.yaml\n+ports\n"
                ),
            )
        if "gitlab.example.com" in url:
            return httpx.Response(
                200,
                json=[{"new_path": "compose.yaml", "old_path": "compose.yaml", "diff": "@@ -1 +1 @@\n+port"}],
            )
        if "git.internal.lan" in url:
            return httpx.Response(200, text="diff --git a/compose.yaml b/compose.yaml\n+ok\n")
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    orig_client = httpx.Client

    def custom_client(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    with patch("httpx.Client", side_effect=custom_client):
        gh_diff = fetch_commit_diff(
            "braz/helios",
            "abc1234",
            matched_files=["compose.yaml"],
            provider="github",
        )
        assert gh_diff is not None
        assert "compose.yaml" in gh_diff
        assert "README.md" not in gh_diff

        gl_diff = fetch_commit_diff(
            "braz/helios",
            "abc1234",
            matched_files=["compose.yaml"],
            provider="gitlab",
            api_url="https://gitlab.example.com",
        )
        assert gl_diff is not None
        assert "+port" in gl_diff

        fj_diff = fetch_commit_diff(
            "braz/helios",
            "abc1234",
            provider="forgejo",
            api_url="https://git.internal.lan",
        )
        assert fj_diff is not None
        assert "+ok" in fj_diff

    # Invalid / latest SHA & error fallback paths
    assert fetch_commit_diff("braz/helios", "latest", provider="github") is None
    assert fetch_commit_diff("braz/helios", "abc1234", provider="forgejo", api_url="") is None

    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    fail_transport = httpx.MockTransport(fail_handler)
    with patch("httpx.Client", side_effect=lambda *a, **kw: orig_client(*a, **{**kw, "transport": fail_transport})):
        assert fetch_commit_diff("braz/helios", "abc1234", provider="github") is None
        assert fetch_commit_diff("braz/helios", "abc1234", provider="gitlab", api_url="https://gitlab.example.com") is None
        assert fetch_commit_diff("braz/helios", "abc1234", provider="forgejo", api_url="https://git.internal.lan") is None

    # Verify JSON error handling in _extract_gemini_json
    from src.semantic import _extract_gemini_json

    assert _extract_gemini_json({"candidates": []}) is None
    assert _extract_gemini_json({"candidates": [{"content": {"parts": [{"text": ""}]}}]}) is None
    parsed_fenced = _extract_gemini_json(
        {"candidates": [{"content": {"parts": [{"text": '```json\n{"ok": true}\n```'}]}}]}
    )
    assert parsed_fenced == {"ok": True}
    parsed_thought = _extract_gemini_json(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "thinking..."},
                            {"text": '{"ok": true}'},
                        ]
                    }
                }
            ]
        }
    )
    assert parsed_thought == {"ok": True}
    assert json.dumps(parsed_fenced) == '{"ok": true}'


def test_analyze_scope_contradictions_sets_thinking_budget_and_timeout(monkeypatch):
    """Contradiction auditor bounds thinkingBudget=2048 and raises default HTTP timeout to >=45s."""
    monkeypatch.setenv("HELIOS_GEMINI_API_KEY", "fake-gemini-key")
    captured: dict = {}
    orig_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": json.dumps({"contradictions": [], "merge_candidates": []})}
                            ]
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)

    def custom_client(*args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    with patch("src.semantic.httpx.Client", side_effect=custom_client):
        result = analyze_scope_contradictions(
            "demo",
            [
                {"id": 1, "scope": "demo", "category": "fact", "content": "One"},
                {"id": 2, "scope": "demo", "category": "fact", "content": "Two"},
            ],
        )

    assert result == {"contradictions": [], "merge_candidates": []}
    assert captured["timeout"] >= 45.0
    assert captured["json"]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 2048}


def test_semantic_zero_norm_and_triage_fail_open_guards(monkeypatch):
    from src.semantic import upsert_memory_embedding

    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    # No key -> embedding upsert is no-op and triage returns None
    with get_connection() as conn:
        upsert_memory_embedding(conn, 1, "subj", "ignored")
    assert triage_webhook_drift_with_gemini("diff", [{"id": 1}], "abc") is None

    # Empty diff / empty candidates / malformed Gemini response -> None (fail open)
    monkeypatch.setenv("HELIOS_GEMINI_API_KEY", "fake-gemini-key")
    assert triage_webhook_drift_with_gemini("", [{"id": 1}], "abc") is None
    assert triage_webhook_drift_with_gemini("diff", [], "abc") is None

    orig_client = httpx.Client
    bad_transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps({"not_decisions": []})}]}}]},
        )
    )
    with patch("src.semantic.httpx.Client", side_effect=lambda *a, **kw: orig_client(*a, **{**kw, "transport": bad_transport})):
        assert triage_webhook_drift_with_gemini("diff", [{"id": 1, "content": "x"}], "abc") is None
