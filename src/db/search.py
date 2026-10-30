"""
Full-Text Search & Synonym-Expanded BM25 Ranking.

Provides FTS5 MATCH query building with 10 bidirectional domain synonym clusters
and column-weighted BM25 ranking (subject 10x, scope 5x, content 1x).
"""

import re
import sqlite3
from typing import Any

from src.db.connection import get_connection, now_iso
from src.db.memories import prune_expired_episodic
from src.db.scopes import resolve_scope

SYNONYM_GROUPS: list[set[str]] = [
    # Database
    {"db", "database", "sql", "postgres", "postgresql", "mysql", "sqlite", "redis", "mongodb", "mongo"},
    # Networking & Ports
    {"port", "ports", "bind", "binding", "listen", "host", "hostname", "address", "ip", "subnet", "cidr"},
    # Auth & Security
    {"auth", "authentication", "login", "token", "jwt", "credentials", "key", "secret", "cert", "certificate", "tls", "ssl"},
    # Environment & Config
    {"env", "environment", "variable", "variables", "config", "configuration", "settings", "conf", "yaml", "toml"},
    # VCS & Repos
    {"repo", "repository", "git", "branch", "commit", "pr", "pull"},
    # Documentation & Rules
    {"doc", "docs", "documentation", "spec", "specification", "rule", "guardrail", "guideline", "policy"},
    # Deployment & Infrastructure
    {"deploy", "deployment", "docker", "compose", "stack", "container", "service", "k8s", "kubernetes", "homelab"},
    # Observability & Monitoring
    {"logs", "logging", "metrics", "monitor", "monitoring", "telemetry", "grafana", "prometheus"},
    # Errors & Debugging
    {"err", "error", "exception", "bug", "crash", "fail", "failure", "debug", "traceback"},
    # API & Transport
    {"api", "endpoint", "route", "http", "rest", "sse", "mcp", "webhook"},
]

_SYNONYM_LOOKUP: dict[str, tuple[str, ...]] = {}
for _group in SYNONYM_GROUPS:
    for _w in _group:
        _SYNONYM_LOOKUP[_w] = tuple(sorted(_group - {_w}))


def build_fts5_query(clean_tokens: list[str]) -> str:
    """
    Construct an FTS5 MATCH expression with synonym expansion.
    For each user token, if matching synonyms exist, creates an OR cluster:
    e.g. '("db"* OR "database"* OR "sql"*)'.
    """
    clusters: list[str] = []
    for raw_tok in clean_tokens[:32]:
        safe_tok = raw_tok.replace("\x00", "").replace('"', '""').strip()
        if not safe_tok:
            continue
        tok_lower = safe_tok.lower()
        synonyms = _SYNONYM_LOOKUP.get(tok_lower, ())
        top_syns = [s for s in synonyms if s != tok_lower][:3]
        if top_syns:
            safe_syns = [s.replace('"', '""') for s in top_syns]
            syn_clauses = " OR ".join(f'"{s}"*' for s in safe_syns)
            clusters.append(f'("{safe_tok}"* OR {syn_clauses})')
        else:
            clusters.append(f'"{safe_tok}"*')
    return " OR ".join(clusters)


def query_memories(
    raw_scope: str = "global",
    query: str = "",
    include_global: bool = True,
    limit: int = 8,
    category: str | None = None,
    status_filter: str = "all",
) -> list[dict[str, Any]]:
    """
    Retrieve active memories using FTS5 BM25 search or prioritized categorical fallback.

    - Prunes expired episodic memories first.
    - Searches both the resolved scope and 'global' (if include_global=True).
    - Clamps limit between 1 and 50.
    - Supports optional category filter ('rule', 'fact', 'preference', 'episodic').
    - Supports status_filter ('all' -> active & stale, 'active' -> active only, 'stale' -> stale only).
    - Increments hit_count and updates last_accessed for returned rows (except for administrative 'stale' audits).
    """
    prune_expired_episodic()

    limit = max(1, min(limit, 50))
    ts = now_iso()

    norm_status = (status_filter or "all").strip().lower()
    if norm_status == "active":
        status_clause_m = "m.status = 'active'"
        status_clause_bare = "status = 'active'"
    elif norm_status == "stale":
        status_clause_m = "m.status = 'stale'"
        status_clause_bare = "status = 'stale'"
    else:
        status_clause_m = "m.status IN ('active', 'stale')"
        status_clause_bare = "status IN ('active', 'stale')"

    cat_clean = category.strip().lower() if category and category.strip() else None
    cat_clause_m = "AND m.category = ?" if cat_clean else ""
    cat_clause_bare = "AND category = ?" if cat_clean else ""
    cat_params = [cat_clean] if cat_clean else []

    with get_connection() as conn:
        scope = resolve_scope(raw_scope, conn=conn)
        scopes = [scope]
        if include_global and scope != "global":
            scopes.append("global")
        placeholders = ",".join("?" for _ in scopes)

        if query.strip():
            # 1. Extract valid words/numbers/tokens, preserving technical punctuation (dots, colons, hyphens)
            clean_query = query.replace('"', ' ').replace('\x00', ' ')
            raw_tokens = re.findall(r"[\w.:-]+", clean_query, flags=re.UNICODE)
            clean_tokens = []
            for tok in raw_tokens:
                t = tok.strip("-_.:*")
                if not t:
                    continue
                if t.upper() in ("AND", "OR", "NOT"):
                    continue
                clean_tokens.append(t)

            # If multiple tokens exist, drop 1-char tokens and common stopwords
            if len(clean_tokens) > 1:
                stopwords = {"the", "is", "in", "to", "of", "for", "on", "with", "at", "by", "an", "be", "as"}
                filtered = [
                    t for t in clean_tokens
                    if len(t) > 1 and t.lower() not in stopwords
                ]
                if filtered:
                    clean_tokens = filtered

            # If user query was only punctuation/operators (e.g. '***:::'), return empty list safely
            if not clean_tokens:
                return []

            # 2. Quote each token as a prefix search cluster with synonym expansion
            fts_query = build_fts5_query(clean_tokens)

            try:
                rows = conn.execute(
                    f"""
                    SELECT m.id, m.scope, m.category, m.subject, m.content,
                           m.status, m.stale_reason, m.anchor_files
                    FROM memories_fts f
                    JOIN memories m ON f.rowid = m.id
                    WHERE m.scope IN ({placeholders})
                      AND {status_clause_m}
                      AND m.valid_to IS NULL
                      {cat_clause_m}
                      AND memories_fts MATCH ?
                    ORDER BY bm25(memories_fts, 5.0, 10.0, 1.0), m.hit_count DESC
                    LIMIT ?
                    """,
                    (*scopes, *cat_params, fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                # Failsafe fallback: return empty list on any syntax anomaly
                return []
        else:
            # Empty query: return rules first, then facts, preferences, episodic
            rows = conn.execute(
                f"""
                SELECT id, scope, category, subject, content, status, stale_reason, anchor_files
                FROM memories
                WHERE scope IN ({placeholders})
                  AND {status_clause_bare}
                  AND valid_to IS NULL
                  {cat_clause_bare}
                ORDER BY
                    CASE category
                        WHEN 'rule' THEN 1
                        WHEN 'fact' THEN 2
                        WHEN 'preference' THEN 3
                        ELSE 4
                    END,
                    hit_count DESC,
                    id DESC
                LIMIT ?
                """,
                (*scopes, *cat_params, limit),
            ).fetchall()

        results = [dict(r) for r in rows]

        # 3. Bump hit_count and refresh last_accessed for returned results (skip for administrative 'stale' audits)
        if results and norm_status != "stale":
            ids = [r["id"] for r in results]
            id_str = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE memories SET hit_count = hit_count + 1, last_accessed = ? WHERE id IN ({id_str}) AND valid_to IS NULL",
                (ts, *ids),
            )

        return results
