"""
Git Anchor Drift & Staleness Tracking.

Inspects Git push commit file changes against memory anchor_files
to flag affected active memories as stale.
"""

import json
import re
from typing import Any

from src.config import get_gemini_api_key, get_git_token
from src.db.connection import get_connection, now_iso
from src.db.scopes import resolve_scope


def _normalize_repo_path(path: str) -> str:
    """Normalize a repo-relative file path, stripping backslashes and redundant prefixes."""
    if not path or not path.strip():
        return ""
    p = path.strip().replace("\\", "/").strip("/")
    while p.startswith("./"):
        p = p[2:].strip("/")
    return p


def flag_stale_by_files(
    repo_name: str,
    modified_files: list[str],
    commit_sha: str,
    diff_text: str | None = None,
) -> int:
    """
    Mark active memories as 'stale' if any of their anchor_files were modified in a Git commit.

    - Normalizes slashes and matches strictly on exact path or '/'-bounded path suffix.
    - When HELIOS_GEMINI_API_KEY is configured and commit diff is available, uses Gemini
      to keep UNCHANGED facts active (stamping last_verified_commit) and flag only affected facts.
    - Returns the count of memories transitioned from active to stale.
    """
    if not modified_files:
        return 0

    short_sha = re.sub(r"[^a-zA-Z0-9._-]", "", commit_sha or "")[:7] or "latest"
    norm_modified = [_normalize_repo_path(f) for f in modified_files[:500] if _normalize_repo_path(f)]
    if not norm_modified:
        return 0

    with get_connection() as conn:
        scope = resolve_scope(repo_name, conn=conn)
        rows = conn.execute(
            """
            SELECT id, subject, content, anchor_files FROM memories
            WHERE scope IN (?, 'global') AND status = 'active' AND valid_to IS NULL
            """,
            (scope,),
        ).fetchall()

    matched_pairs: list[tuple[dict[str, Any], str]] = []
    for row in rows:
        try:
            raw_anchors = json.loads(row["anchor_files"] or "[]")
        except Exception:
            raw_anchors = []
        norm_anchors = [_normalize_repo_path(a) for a in raw_anchors if _normalize_repo_path(a)]

        matched_file = None
        for mod_file in norm_modified:
            for anchor in norm_anchors:
                if mod_file == anchor or mod_file.endswith("/" + anchor):
                    matched_file = mod_file
                    break
            if matched_file:
                break

        if matched_file:
            matched_pairs.append((dict(row), matched_file))

    if not matched_pairs:
        return 0

    decisions: dict[int, dict[str, str]] | None = None
    if get_gemini_api_key():
        resolved_diff = diff_text
        if resolved_diff is None and get_git_token() and short_sha != "latest":
            from src.webhooks import fetch_commit_diff

            resolved_diff = fetch_commit_diff(
                repo_name=repo_name,
                commit_sha=commit_sha,
                matched_files=[m[1] for m in matched_pairs],
            )
        if resolved_diff:
            from src.semantic import triage_webhook_drift_with_gemini

            candidates = [
                {
                    "id": item["id"],
                    "subject": item["subject"],
                    "content": item["content"],
                    "matched_file": mfile,
                }
                for item, mfile in matched_pairs
            ]
            decisions = triage_webhook_drift_with_gemini(resolved_diff, candidates, short_sha)

    flagged_count = 0
    ts_now = now_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for item, matched_file in matched_pairs:
            mid = item["id"]
            decision = (decisions or {}).get(mid)
            if decision and decision.get("status") == "UNCHANGED":
                conn.execute(
                    """
                    UPDATE memories
                    SET last_verified_commit = ?
                    WHERE id = ? AND status = 'active' AND valid_to IS NULL
                    """,
                    (short_sha, mid),
                )
                continue

            gem_reason = (decision or {}).get("reason", "").strip()
            if gem_reason:
                reason = f"{gem_reason} ({short_sha})"[:200]
            else:
                clean_matched = re.sub(r"[^a-zA-Z0-9_./-]", "", matched_file)[:120]
                reason = f"{clean_matched} modified in commit {short_sha}"

            cur = conn.execute(
                """
                UPDATE memories
                SET status = 'stale', stale_reason = ?, stale_since = ?
                WHERE id = ? AND status = 'active' AND valid_to IS NULL
                """,
                (reason, ts_now, mid),
            )
            flagged_count += cur.rowcount

    return flagged_count
