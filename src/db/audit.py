"""
Memory Distillation & Hygiene Auditing.

Performs scope health scans, word count statistics, expired episodic identification,
stale drift backlog detection, cold memory detection, token Jaccard similarity
slot collision analysis, and bulk pruning.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from src.config import get_episodic_ttl_days
from src.db.connection import get_connection, get_db_path, now_iso
from src.db.scopes import resolve_scope


def db_audit_memories(
    raw_scope: str = "global",
    stale_age_days: int = 30,
) -> dict[str, Any]:
    """
    Audit memory hygiene for a specific scope or all scopes.
    Returns:
    - scope stats (active, stale, archived, word count)
    - expired episodic candidates
    - stale backlog older than stale_age_days
    - cold memories (0 hits, unaccessed > 30 days)
    - candidate slot collisions / near-duplicates within the scope
    """
    if not get_db_path().exists():
        return {
            "scope": raw_scope,
            "total_active": 0,
            "total_stale": 0,
            "total_archived": 0,
            "total_words": 0,
            "avg_words": 0.0,
            "expired_episodic": [],
            "stale_backlog": [],
            "cold_memories": [],
            "potential_collisions": [],
        }

    ttl_days = get_episodic_ttl_days()
    now_dt = datetime.now(UTC)
    episodic_cutoff = (now_dt - timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_cutoff = (now_dt - timedelta(days=stale_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cold_cutoff = (now_dt - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_connection() as conn:
        all_scopes_mode = raw_scope.strip().lower() in ("all", "*", "")
        if all_scopes_mode:
            target_scopes = None
        else:
            resolved = resolve_scope(raw_scope, conn=conn)
            target_scopes = [resolved]

        scope_clause = ""
        params: list[Any] = []
        if target_scopes:
            scope_clause = "AND scope = ?"
            params.append(target_scopes[0])

        # Active & stale memories
        active_rows = conn.execute(
            f"""
            SELECT id, scope, category, subject, content, status, stale_reason, stale_since,
                   anchor_files, valid_from, last_accessed, hit_count
            FROM memories
            WHERE status IN ('active', 'stale') AND valid_to IS NULL {scope_clause}
            ORDER BY scope, id
            """,
            params,
        ).fetchall()

        # Archived count
        archived_count = conn.execute(
            f"SELECT COUNT(*) FROM memories WHERE status = 'archived' {scope_clause}",
            params,
        ).fetchone()[0]

        total_active = sum(1 for r in active_rows if r["status"] == "active")
        total_stale = sum(1 for r in active_rows if r["status"] == "stale")

        # Word counts
        word_counts = [len(r["content"].split()) for r in active_rows]
        total_words = sum(word_counts)
        avg_words = round(total_words / len(word_counts), 1) if word_counts else 0.0

        # Expired episodic
        expired_episodic = [
            {
                "id": r["id"],
                "scope": r["scope"],
                "subject": r["subject"],
                "content": r["content"],
                "last_accessed": r["last_accessed"],
            }
            for r in active_rows
            if r["category"] == "episodic" and r["last_accessed"] < episodic_cutoff
        ]

        # Stale backlog older than stale_age_days
        stale_backlog = [
            {
                "id": r["id"],
                "scope": r["scope"],
                "subject": r["subject"],
                "stale_reason": r["stale_reason"],
                "content": r["content"],
                "valid_from": r["valid_from"],
            }
            for r in active_rows
            if r["status"] == "stale" and (r["stale_since"] or r["valid_from"]) < stale_cutoff
        ]

        # Cold memories (0 hits, active only, unaccessed > 30 days)
        cold_memories = [
            {
                "id": r["id"],
                "scope": r["scope"],
                "subject": r["subject"],
                "content": r["content"],
                "last_accessed": r["last_accessed"],
            }
            for r in active_rows
            if r["status"] == "active" and r["hit_count"] == 0 and r["last_accessed"] < cold_cutoff
        ]

        # Collision detection (group by scope first, then compare active memories within scope)
        potential_collisions: list[dict[str, Any]] = []
        by_scope: dict[str, list[dict[str, Any]]] = {}
        for r in active_rows:
            if r["status"] == "active":
                by_scope.setdefault(r["scope"], []).append(dict(r))

        stopwords = {
            "the", "is", "in", "to", "of", "for", "on", "with", "at", "by", "an", "be", "as", "and", "or", "a"
        }
        for s_name, mems in by_scope.items():
            if len(mems) < 2:
                continue
            mem_tokens: list[tuple[dict[str, Any], set[str]]] = []
            for m in mems:
                text = f"{m['subject']} {m['content']}".lower()
                toks = {
                    w.strip(".,;:?!-_()[]'\"")
                    for w in text.split()
                    if len(w.strip(".,;:?!-_()[]'\"")) > 2 and w.lower() not in stopwords
                }
                mem_tokens.append((m, toks))

            for i in range(len(mem_tokens)):
                for j in range(i + 1, len(mem_tokens)):
                    m1, t1 = mem_tokens[i]
                    m2, t2 = mem_tokens[j]
                    if not t1 or not t2:
                        continue
                    intersection = t1 & t2
                    union = t1 | t2
                    jaccard = len(intersection) / len(union) if union else 0.0
                    if jaccard >= 0.50 or (len(intersection) >= 3 and jaccard >= 0.35):
                        potential_collisions.append({
                            "scope": s_name,
                            "similarity": round(jaccard, 2),
                            "shared_terms": sorted(intersection),
                            "mem1": {"id": m1["id"], "subject": m1["subject"], "content": m1["content"]},
                            "mem2": {"id": m2["id"], "subject": m2["subject"], "content": m2["content"]},
                        })

        return {
            "scope": "all" if all_scopes_mode else target_scopes[0],
            "total_active": total_active,
            "total_stale": total_stale,
            "total_archived": archived_count,
            "total_words": total_words,
            "avg_words": avg_words,
            "expired_episodic": expired_episodic,
            "stale_backlog": stale_backlog,
            "cold_memories": cold_memories,
            "potential_collisions": potential_collisions,
        }


def db_prune_memories(
    raw_scope: str = "global",
    prune_stale: bool = True,
    stale_age_days: int = 30,
) -> dict[str, Any]:
    """
    Prune (archive) expired episodic memories and optionally old unreviewed stale memories.
    """
    if not get_db_path().exists():
        return {"scope": raw_scope, "pruned_episodic": 0, "pruned_stale": 0, "archived_ids": []}

    ttl_days = get_episodic_ttl_days()
    now_dt = datetime.now(UTC)
    episodic_cutoff = (now_dt - timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_cutoff = (now_dt - timedelta(days=stale_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts = now_iso()

    with get_connection() as conn:
        all_scopes_mode = raw_scope.strip().lower() in ("all", "*", "")
        if all_scopes_mode:
            target_scope = None
        else:
            target_scope = resolve_scope(raw_scope, conn=conn)

        scope_clause = "AND scope = ?" if target_scope else ""
        params_episodic: list[Any] = [ts, episodic_cutoff]
        params_stale: list[Any] = [ts, stale_cutoff]
        if target_scope:
            params_episodic.append(target_scope)
            params_stale.append(target_scope)

        conn.execute("BEGIN IMMEDIATE")

        # 1. Prune expired episodic
        cur_episodic = conn.execute(
            f"""
            UPDATE memories
            SET status = 'archived', valid_to = ?
            WHERE category = 'episodic'
              AND last_accessed < ?
              AND status IN ('active', 'stale')
              {scope_clause}
            RETURNING id
            """,
            params_episodic,
        )
        pruned_episodic_ids = [row[0] for row in cur_episodic.fetchall()]

        # 2. Prune old stale
        pruned_stale_ids: list[int] = []
        if prune_stale:
            cur_stale = conn.execute(
                f"""
                UPDATE memories
                SET status = 'archived', valid_to = ?
                WHERE status = 'stale'
                  AND COALESCE(stale_since, valid_from) < ?
                  AND valid_to IS NULL
                  {scope_clause}
                RETURNING id
                """,
                params_stale,
            )
            pruned_stale_ids = [row[0] for row in cur_stale.fetchall()]

        return {
            "scope": "all" if all_scopes_mode else target_scope,
            "pruned_episodic": len(pruned_episodic_ids),
            "pruned_stale": len(pruned_stale_ids),
            "archived_ids": sorted(pruned_episodic_ids + pruned_stale_ids),
        }
