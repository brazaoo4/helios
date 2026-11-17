"""
Optional Gemini Semantic Search (Matryoshka RRF), Diff-Aware Drift Triage,
and Contradiction Auditing.

Zero extra pip dependencies: uses stdlib array/math/json and existing httpx.
All features gracefully degrade or remain disabled when HELIOS_GEMINI_API_KEY is unset.
"""

import json
import logging
import math
import re
import sqlite3
import sys
from array import array
from typing import Any

import httpx

from src.config import get_gemini_api_key, get_semantic_search_enabled
from src.db.connection import get_connection
from src.security_gate import redact_secrets

logger = logging.getLogger("helios.semantic")

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMS = 256
TRIAGE_MODEL = "gemini-flash-lite-latest"
AUDITOR_MODEL = "gemini-flash-latest"

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_CAT_TIE_BOOST = {"rule": 0.0015, "fact": 0.001, "preference": 0.0005, "episodic": 0.0}


def pack_embedding(values: list[float]) -> bytes:
    """L2-normalize a float vector and pack as little-endian float32 bytes."""
    norm = math.sqrt(sum(v * v for v in values))
    if norm > 0.0:
        normed = [v / norm for v in values]
    else:
        normed = list(values)
    arr = array("f", normed)
    if sys.byteorder == "big":  # pragma: no cover
        arr.byteswap()
    return arr.tobytes()


def unpack_embedding(blob: bytes) -> array:
    """Unpack little-endian float32 bytes into a Python array('f')."""
    arr = array("f")
    arr.frombytes(blob)
    if sys.byteorder == "big":  # pragma: no cover
        arr.byteswap()
    return arr


def cosine_similarity(vec_a: Any, vec_b: Any) -> float:
    """Compute dot-product cosine similarity between equal-length vectors."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    return sum(a * b for a, b in zip(vec_a, vec_b))


def fetch_gemini_embedding(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
    timeout: float = 4.0,
) -> list[float] | None:
    """Fetch a 256-d Matryoshka embedding from Gemini REST API, failing open on errors."""
    api_key = get_gemini_api_key()
    if not api_key or not get_semantic_search_enabled():
        return None
    clean_text = text.strip()
    if not clean_text:
        return None

    url = f"{_GEMINI_API_BASE}/{EMBEDDING_MODEL}:embedContent"
    payload = {
        "model": f"models/{EMBEDDING_MODEL}",
        "content": {"parts": [{"text": clean_text[:2000]}]},
        "taskType": task_type,
        "outputDimensionality": EMBEDDING_DIMS,
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
            if res.status_code != 200:
                logger.warning(
                    "Gemini embedContent returned HTTP %d: %s",
                    res.status_code,
                    redact_secrets(res.text[:200]),
                )
                return None
            data = res.json()
        values = (data.get("embedding") or {}).get("values")
        if not isinstance(values, list) or len(values) != EMBEDDING_DIMS:
            return None
        return [float(v) for v in values]
    except Exception as exc:
        logger.warning("Gemini embedContent failed (failing open): %s", redact_secrets(str(exc)))
        return None


def upsert_memory_embedding(memory_id: int, scope: str, subject: str, content: str) -> bool:
    """Generate and persist a 256-d embedding for a saved memory (fail-open)."""
    if not get_semantic_search_enabled():
        return False
    doc_text = f"{scope} {subject}: {content}".strip() if subject else f"{scope}: {content}"
    values = fetch_gemini_embedding(doc_text, task_type="RETRIEVAL_DOCUMENT")
    if not values:
        return False
    blob = pack_embedding(values)
    try:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO memory_embeddings (memory_id, model, dims, vec)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    model = excluded.model,
                    dims = excluded.dims,
                    vec = excluded.vec
                """,
                (memory_id, EMBEDDING_MODEL, EMBEDDING_DIMS, blob),
            )
        return True
    except Exception as exc:
        logger.warning("Failed storing embedding for memory #%d: %s", memory_id, redact_secrets(str(exc)))
        return False


def semantic_search_memories(
    conn: sqlite3.Connection,
    scopes: list[str],
    query: str,
    status_clause_m: str,
    cat_clause_m: str,
    cat_params: list[Any],
    limit: int = 20,
    min_similarity: float = 0.35,
) -> list[dict[str, Any]]:
    """Score active/stale memory vectors in scopes via cosine similarity against the query vector."""
    if not get_semantic_search_enabled() or not scopes or not query.strip():
        return []
    q_values = fetch_gemini_embedding(query.strip(), task_type="RETRIEVAL_QUERY")
    if not q_values:
        return []
    q_vec = unpack_embedding(pack_embedding(q_values))

    placeholders = ",".join("?" for _ in scopes)
    rows = conn.execute(
        f"""
        SELECT m.id, m.scope, m.category, m.subject, m.content,
               m.status, m.stale_reason, m.anchor_files, e.vec
        FROM memory_embeddings e
        JOIN memories m ON e.memory_id = m.id
        WHERE m.scope IN ({placeholders})
          AND {status_clause_m}
          AND m.valid_to IS NULL
          {cat_clause_m}
          AND e.dims = ?
        """,
        (*scopes, *cat_params, EMBEDDING_DIMS),
    ).fetchall()

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        item = dict(row)
        vec_blob = item.pop("vec")
        sim = cosine_similarity(q_vec, unpack_embedding(vec_blob))
        if sim >= min_similarity:
            scored.append((sim, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:limit]]


def reciprocal_rank_fusion(
    lexical_rows: list[dict[str, Any]],
    semantic_rows: list[dict[str, Any]],
    limit: int,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Fuse lexical FTS5 and semantic vector rankings using Reciprocal Rank Fusion."""
    scores: dict[int, float] = {}
    records: dict[int, dict[str, Any]] = {}

    for rank, row in enumerate(lexical_rows, 1):
        mid = row["id"]
        records[mid] = row
        scores[mid] = scores.get(mid, 0.0) + (1.0 / (rrf_k + rank))

    for rank, row in enumerate(semantic_rows, 1):
        mid = row["id"]
        if mid not in records:
            records[mid] = row
        scores[mid] = scores.get(mid, 0.0) + (1.0 / (rrf_k + rank))

    for mid, row in records.items():
        if row.get("status") == "active":
            scores[mid] += 0.002
        scores[mid] += _CAT_TIE_BOOST.get(row.get("category", ""), 0.0)

    ranked_ids = sorted(records.keys(), key=lambda mid: scores[mid], reverse=True)
    return [records[mid] for mid in ranked_ids[:limit]]


def _extract_gemini_json(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract and parse the JSON payload returned by Gemini generateContent."""
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    raw_text = ""
    for part in parts:
        if not isinstance(part, dict) or part.get("thought") is True:
            continue
        candidate_text = str(part.get("text") or "").strip()
        if candidate_text:
            raw_text = candidate_text
            break
    if not raw_text:
        return None
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.DOTALL).strip()
    parsed = json.loads(raw_text)
    return parsed if isinstance(parsed, dict) else None


def triage_webhook_drift_with_gemini(
    diff_text: str,
    candidates: list[dict[str, Any]],
    commit_sha: str,
    timeout: float = 6.0,
) -> dict[int, dict[str, str]] | None:
    """
    Evaluate whether a Git commit diff invalidates candidate anchored memories.
    Returns {memory_id: {"status": "UNCHANGED"|"STALE", "reason": str}} or None on fallback.
    """
    api_key = get_gemini_api_key()
    if not api_key or not diff_text.strip() or not candidates:
        return None

    candidate_lines = [
        {
            "id": c["id"],
            "subject": c.get("subject", ""),
            "content": c.get("content", ""),
            "matched_file": c.get("matched_file", ""),
        }
        for c in candidates[:50]
    ]
    prompt = (
        "You are triaging whether a Git commit diff invalidates stored architectural facts.\n"
        "For EACH candidate memory, decide:\n"
        "- UNCHANGED: the diff does NOT contradict or modify the specific fact.\n"
        "- STALE: the diff contradicts, removes, renames, or potentially alters the fact.\n"
        "Return strict JSON matching the schema with a concise reason (<= 15 words) when STALE.\n\n"
        f"Commit: {commit_sha}\n"
        f"Candidates:\n{json.dumps(candidate_lines)}\n\n"
        f"Git Diff (truncated to 16KB):\n{diff_text[:16384]}"
    )

    url = f"{_GEMINI_API_BASE}/{TRIAGE_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0,
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "decisions": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "id": {"type": "INTEGER"},
                                "status": {"type": "STRING", "enum": ["UNCHANGED", "STALE"]},
                                "reason": {"type": "STRING"},
                            },
                            "required": ["id", "status", "reason"],
                        },
                    }
                },
                "required": ["decisions"],
            },
        },
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=body,
            )
            if res.status_code != 200:
                logger.warning(
                    "Gemini triage returned HTTP %d: %s",
                    res.status_code,
                    redact_secrets(res.text[:200]),
                )
                return None
            parsed = _extract_gemini_json(res.json())
        if not parsed or not isinstance(parsed.get("decisions"), list):
            return None

        decisions: dict[int, dict[str, str]] = {}
        for item in parsed["decisions"]:
            if not isinstance(item, dict) or "id" not in item:
                continue
            mid = int(item["id"])
            raw_status = str(item.get("status", "STALE")).strip().upper()
            norm_status = "UNCHANGED" if raw_status == "UNCHANGED" else "STALE"
            clean_reason = re.sub(r"[\r\n`]+", " ", str(item.get("reason", ""))).strip()[:140]
            decisions[mid] = {"status": norm_status, "reason": clean_reason}
        return decisions
    except Exception as exc:
        logger.warning("Gemini webhook triage failed (falling back): %s", redact_secrets(str(exc)))
        return None


def analyze_scope_contradictions(
    scope: str,
    active_memories: list[dict[str, Any]],
    timeout: float = 20.0,
) -> dict[str, Any]:
    """
    Use Gemini Flash to identify semantic contradictions and merge candidates
    across active memories in a scope.
    """
    api_key = get_gemini_api_key()
    if not api_key:
        raise ValueError("HELIOS_GEMINI_API_KEY is not configured.")
    if len(active_memories) < 2:
        return {"contradictions": [], "merge_candidates": []}

    items = [
        {
            "id": m["id"],
            "scope": m["scope"],
            "category": m["category"],
            "subject": m.get("subject", ""),
            "content": m["content"],
        }
        for m in active_memories[:100]
    ]
    prompt = (
        f"Audit active architectural memories for scope '{scope}'.\n"
        "Identify:\n"
        "1. contradictions: pairs of memories that state conflicting ports, hosts, tools, or rules.\n"
        "2. merge_candidates: pairs of redundant or overlapping memories that should be consolidated.\n"
        "For each pair provide id1, id2, summary, and a suggested consolidated_content (<= 25 words).\n\n"
        f"Memories:\n{json.dumps(items)}"
    )

    pair_schema = {
        "type": "OBJECT",
        "properties": {
            "id1": {"type": "INTEGER"},
            "id2": {"type": "INTEGER"},
            "summary": {"type": "STRING"},
            "consolidated_content": {"type": "STRING"},
        },
        "required": ["id1", "id2", "summary", "consolidated_content"],
    }

    url = f"{_GEMINI_API_BASE}/{AUDITOR_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "contradictions": {"type": "ARRAY", "items": pair_schema},
                    "merge_candidates": {"type": "ARRAY", "items": pair_schema},
                },
                "required": ["contradictions", "merge_candidates"],
            },
        },
    }

    with httpx.Client(timeout=timeout) as client:
        res = client.post(
            url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=body,
        )
        if res.status_code != 200:
            raise RuntimeError(
                f"Gemini contradiction audit failed with HTTP {res.status_code}: {redact_secrets(res.text[:200])}"
            )
        parsed = _extract_gemini_json(res.json()) or {}

    return {
        "contradictions": parsed.get("contradictions") if isinstance(parsed.get("contradictions"), list) else [],
        "merge_candidates": parsed.get("merge_candidates") if isinstance(parsed.get("merge_candidates"), list) else [],
    }


__all__ = [
    "AUDITOR_MODEL",
    "EMBEDDING_DIMS",
    "EMBEDDING_MODEL",
    "TRIAGE_MODEL",
    "analyze_scope_contradictions",
    "cosine_similarity",
    "fetch_gemini_embedding",
    "pack_embedding",
    "reciprocal_rank_fusion",
    "semantic_search_memories",
    "triage_webhook_drift_with_gemini",
    "unpack_embedding",
    "upsert_memory_embedding",
]
