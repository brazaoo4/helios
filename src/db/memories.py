"""
Core Memory Lifecycle & AUDN Write Gate.

Enforces category constraints, strict word budgets, slot supersession,
duplicate detection, explicit deprecation, revalidation, and episodic TTL pruning.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from src.config import get_episodic_ttl_days, get_word_limit
from src.db.connection import get_connection, get_db_path, now_iso
from src.db.drift import _normalize_repo_path
from src.db.scopes import resolve_scope


def prune_expired_episodic() -> int:
    """
    Archive temporary 'episodic' memories unaccessed for more than HELIOS_EPISODIC_TTL_DAYS days.

    Sets status='archived' and valid_to=now_iso().
    Leaves rules, facts, preferences, and recent episodic memories untouched.
    Returns the count of archived rows.
    """
    if not get_db_path().exists():
        return 0

    ttl_days = get_episodic_ttl_days()
    cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_connection() as conn:
        has_expired = conn.execute(
            "SELECT 1 FROM memories WHERE category = 'episodic' AND last_accessed < ? AND status IN ('active', 'stale') LIMIT 1",
            (cutoff,),
        ).fetchone()
        if not has_expired:
            return 0

        conn.execute("BEGIN IMMEDIATE")
        ts = now_iso()
        cur = conn.execute(
            """
            UPDATE memories
            SET status = 'archived', valid_to = ?
            WHERE category = 'episodic'
                AND last_accessed < ?
                AND status IN ('active', 'stale')
            """,
            (ts, cutoff),
        )
        return cur.rowcount


def upsert_memory(
    raw_scope: str,
    category: str,
    content: str,
    subject: str = "",
    anchor_files: list[str] | None = None,
    replaces_id: int | None = None,
) -> dict[str, Any]:
    """
    AUDN Write Gate:
    - Enforces category validation and a strict word limit (HELIOS_WORD_LIMIT).
    - Locks transaction with BEGIN IMMEDIATE to prevent write collisions.
    - Duplicate detection: returns 'no-op' and refreshes last_accessed.
    - Slot supersession: automatically retires older active records sharing (scope, subject).
    - Explicit supersession: validates and retires replaces_id if provided.
    """
    valid_categories = ("rule", "fact", "preference", "episodic")
    if category not in valid_categories:
        raise ValueError(f"Invalid category '{category}'. Must be one of: {valid_categories}")

    # Normalize whitespace (strip leading/trailing, collapse multiple spaces into one)
    content_clean = " ".join(content.strip().split())
    if not content_clean:
        raise ValueError("Memory content cannot be empty.")

    word_limit = get_word_limit()
    word_count = len(content_clean.split())
    if word_count > word_limit:
        raise ValueError(
            f"Content exceeds {word_limit}-word limit ({word_count} words; remove at least {word_count - word_limit} words). Keep facts atomic."
        )

    subject_clean = subject.strip().lower()
    normalized_anchors = list(
        dict.fromkeys(_normalize_repo_path(a) for a in (anchor_files or []) if _normalize_repo_path(a))
    )
    anchors_json = json.dumps(normalized_anchors)
    ts = now_iso()

    with get_connection() as conn:
        # BEGIN IMMEDIATE acquires a write lock up-front to prevent concurrent writer collisions
        conn.execute("BEGIN IMMEDIATE")
        scope = resolve_scope(raw_scope, conn=conn)

        # 1. Exact Duplicate Check (No-op or superseded if replaces_id passed)
        existing = conn.execute(
            """
            SELECT id FROM memories
            WHERE scope = ? AND category = ? AND subject = ? AND content = ? AND valid_to IS NULL
            """,
            (scope, category, subject_clean, content_clean),
        ).fetchone()

        if existing:
            superseded_ids = []
            if replaces_id is not None and replaces_id != existing["id"]:
                old_rec = conn.execute(
                    "SELECT id, scope FROM memories WHERE id = ? AND valid_to IS NULL",
                    (replaces_id,),
                ).fetchone()
                if not old_rec:
                    raise ValueError(f"replaces_id {replaces_id} does not exist or is already superseded.")
                if resolve_scope(old_rec["scope"], conn=conn) != scope:
                    raise ValueError(
                        f"Cannot supersede memory across different scopes ('{old_rec['scope']}' -> '{scope}')."
                    )
                conn.execute(
                    "UPDATE memories SET status = 'superseded', valid_to = ?, superseded_by = ? WHERE id = ?",
                    (ts, existing["id"], replaces_id),
                )
                superseded_ids.append(replaces_id)

            update_fields = ["status = 'active'", "stale_reason = ''", "last_accessed = ?"]
            params: list[Any] = [ts]
            if anchor_files is not None:
                update_fields.append("anchor_files = ?")
                params.append(anchors_json)
            params.append(existing["id"])
            conn.execute(
                f"UPDATE memories SET {', '.join(update_fields)} WHERE id = ?",
                tuple(params),
            )
            action = "superseded" if superseded_ids else "no-op (verified existing)"
            return {
                "action": action,
                "id": existing["id"],
                "scope": scope,
                "superseded_ids": superseded_ids,
            }

        # 2. Validate explicit replaces_id (if supplied)
        if replaces_id is not None:
            old_rec = conn.execute(
                "SELECT id, scope FROM memories WHERE id = ? AND valid_to IS NULL",
                (replaces_id,),
            ).fetchone()
            if not old_rec:
                raise ValueError(f"replaces_id {replaces_id} does not exist or is already superseded.")
            if resolve_scope(old_rec["scope"], conn=conn) != scope:
                raise ValueError(
                    f"Cannot supersede memory across different scopes ('{old_rec['scope']}' -> '{scope}')."
                )

        # 3. Insert New Memory Row
        cur = conn.execute(
            """
            INSERT INTO memories (
                scope, category, subject, content, status, anchor_files, valid_from, last_accessed
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (scope, category, subject_clean, content_clean, anchors_json, ts, ts),
        )
        new_id = cur.lastrowid
        superseded_ids = []

        # 4. Retire explicit replaces_id
        if replaces_id is not None:
            conn.execute(
                "UPDATE memories SET status = 'superseded', valid_to = ?, superseded_by = ? WHERE id = ?",
                (ts, new_id, replaces_id),
            )
            superseded_ids.append(replaces_id)

        # 5. Slot Supersession: Retire older active rows in the same (scope, subject) slot
        if subject_clean:
            old_slots = conn.execute(
                """
                SELECT id FROM memories
                WHERE scope = ? AND subject = ? AND id != ? AND valid_to IS NULL
                """,
                (scope, subject_clean, new_id),
            ).fetchall()
            for row in old_slots:
                if row["id"] not in superseded_ids:
                    conn.execute(
                        "UPDATE memories SET status = 'superseded', valid_to = ?, superseded_by = ? WHERE id = ?",
                        (ts, new_id, row["id"]),
                    )
                    superseded_ids.append(row["id"])

        return {
            "action": "superseded" if superseded_ids else "created",
            "id": new_id,
            "scope": scope,
            "superseded_ids": superseded_ids,
        }


def deprecate_memory(memory_id: int, reason: str = "") -> dict[str, Any]:
    """
    AUDN Deprecate Gate:
    Retires an active or stale memory into 'archived' status with valid_to stamped.
    """
    ts = now_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, scope, subject, content, status FROM memories WHERE id = ? AND valid_to IS NULL",
            (memory_id,),
        ).fetchone()

        if not row:
            raise ValueError(f"Memory #{memory_id} does not exist or is already inactive.")

        stale_reason = reason.strip() if reason.strip() else "deprecated by user/agent"
        conn.execute(
            "UPDATE memories SET status = 'archived', valid_to = ?, stale_reason = ? WHERE id = ?",
            (ts, stale_reason, memory_id),
        )

        return {
            "action": "deprecated",
            "id": memory_id,
            "scope": row["scope"],
            "subject": row["subject"],
            "content": row["content"],
        }


def revalidate_memories(memory_ids: list[int]) -> dict[str, Any]:
    """
    Batch revalidate stale memories back to 'active' status.
    For matching rows where status = 'stale' and valid_to IS NULL:
      - sets status = 'active', stale_reason = '', last_accessed = now_iso()
    Returns {"revalidated_ids": [...], "not_found_or_not_stale_ids": [...]}.
    """
    if not memory_ids:
        return {"revalidated_ids": [], "not_found_or_not_stale_ids": []}

    unique_ids = list(dict.fromkeys(memory_ids))
    ts = now_iso()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in unique_ids)
        rows = conn.execute(
            f"SELECT id, status, valid_to FROM memories WHERE id IN ({placeholders})",
            unique_ids,
        ).fetchall()

        stale_ids = {r["id"] for r in rows if r["status"] == "stale" and r["valid_to"] is None}

        if stale_ids:
            update_placeholders = ",".join("?" for _ in stale_ids)
            conn.execute(
                f"""
                UPDATE memories
                SET status = 'active', stale_reason = '', last_accessed = ?
                WHERE id IN ({update_placeholders})
                """,
                (ts, *stale_ids),
            )

        revalidated = [mid for mid in unique_ids if mid in stale_ids]
        not_found_or_not_stale = [mid for mid in unique_ids if mid not in stale_ids]

        return {
            "revalidated_ids": revalidated,
            "not_found_or_not_stale_ids": not_found_or_not_stale,
        }
