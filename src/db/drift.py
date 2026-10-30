"""
Git Anchor Drift & Staleness Tracking.

Inspects Git push commit file changes against memory anchor_files
to flag affected active memories as stale.
"""

import json
import re

from src.db.connection import get_connection
from src.db.scopes import resolve_scope


def _normalize_repo_path(path: str) -> str:
    """Normalize a repo-relative file path, stripping backslashes and redundant prefixes."""
    if not path or not path.strip():
        return ""
    p = path.strip().replace("\\", "/").strip("/")
    while p.startswith("./"):
        p = p[2:].strip("/")
    return p


def flag_stale_by_files(repo_name: str, modified_files: list[str], commit_sha: str) -> int:
    """
    Mark active memories as 'stale' if any of their anchor_files were modified in a Git commit.

    - Normalizes slashes and matches strictly on exact path or '/'-bounded path suffix.
    - Sets status='stale' and stale_reason='<matched_file> modified in commit <short_sha>'.
    - Returns the count of memories transitioned from active to stale.
    """
    if not modified_files:
        return 0

    short_sha = re.sub(r"[^a-zA-Z0-9._-]", "", commit_sha or "")[:7] or "latest"
    norm_modified = [_normalize_repo_path(f) for f in modified_files if _normalize_repo_path(f)]
    if not norm_modified:
        return 0

    flagged_count = 0
    with get_connection() as conn:
        scope = resolve_scope(repo_name, conn=conn)
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT id, anchor_files FROM memories
            WHERE scope IN (?, 'global') AND status = 'active' AND valid_to IS NULL
            """,
            (scope,),
        ).fetchall()

        for row in rows:
            try:
                raw_anchors = json.loads(row["anchor_files"] or "[]")
            except Exception:
                raw_anchors = []
            norm_anchors = [_normalize_repo_path(a) for a in raw_anchors if _normalize_repo_path(a)]

            matched_file = None
            for mod_file in norm_modified:
                for anchor in norm_anchors:
                    # Match only on exact path equality or clean '/' path boundary suffix
                    if mod_file == anchor or mod_file.endswith("/" + anchor):
                        matched_file = mod_file
                        break
                if matched_file:
                    break

            if matched_file:
                clean_matched = re.sub(r"[^a-zA-Z0-9_./-]", "", matched_file)[:120]
                reason = f"{clean_matched} modified in commit {short_sha}"
                conn.execute(
                    "UPDATE memories SET status = 'stale', stale_reason = ? WHERE id = ?",
                    (reason, row["id"]),
                )
                flagged_count += 1

    return flagged_count
