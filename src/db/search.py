"""
Full-Text Search & Synonym-Expanded BM25 Ranking.

Provides Porter-stemmed FTS5 MATCH query building with domain synonym clusters,
compound/version sub-token matching, scoped pre-flight quotas, and weighted BM25 ranking.
"""

import logging
import math
import re
import sqlite3
from typing import Any

from src.config import get_semantic_search_enabled
from src.db.connection import get_connection, now_iso
from src.db.memories import prune_expired_episodic
from src.db.scopes import resolve_scope

logger = logging.getLogger("helios.search")

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

_VERSION_TOKEN_RE = re.compile(r"^[vV]?\d+(?:\.\d+)+$")
_COMPOUND_SEP_RE = re.compile(r"[-_./:]+")
_CATEGORY_RANK = {"rule": 1, "fact": 2, "preference": 3, "episodic": 4}


def _lookup_synonyms(word: str) -> tuple[str, ...]:
    """Look up domain synonyms for word or its singularized stem."""
    w = word.lower()
    if w in _SYNONYM_LOOKUP:
        return _SYNONYM_LOOKUP[w]
    if w.endswith("ies") and len(w) > 3:
        cand = w[:-3] + "y"
        if cand in _SYNONYM_LOOKUP:
            return _SYNONYM_LOOKUP[cand]
    if w.endswith("s") and len(w) > 2:
        cand = w[:-1]
        if cand in _SYNONYM_LOOKUP:
            return _SYNONYM_LOOKUP[cand]
    if w.endswith("es") and len(w) > 3:
        cand = w[:-2]
        if cand in _SYNONYM_LOOKUP:
            return _SYNONYM_LOOKUP[cand]
    return ()


def build_fts5_query(clean_tokens: list[str]) -> str:
    """
    Construct an FTS5 MATCH expression with version normalization,
    compound sub-token expansion, and domain synonym clusters.
    """
    clusters: list[str] = []
    for raw_tok in clean_tokens[:32]:
        safe_tok = raw_tok.replace("\x00", "").replace('"', '""').strip()
        if not safe_tok:
            continue
        if len(safe_tok) == 1:
            if safe_tok.isdigit():
                clusters.append(f'"{safe_tok}"')
            continue

        tok_lower = safe_tok.lower()
        if _VERSION_TOKEN_RE.match(safe_tok):
            num_ver = safe_tok.lstrip("vV")
            clusters.append(f'("{num_ver}"* OR "v{num_ver}"*)')
            continue

        if _COMPOUND_SEP_RE.search(safe_tok):
            subparts = [
                p for p in _COMPOUND_SEP_RE.split(tok_lower)
                if len(p) >= 2 and not p.isdigit()
            ]
            sub_clauses = [f'"{safe_tok}"*']
            if len(subparts) >= 2:
                and_expr = " AND ".join(f'"{p.replace(chr(34), chr(34) * 2)}"*' for p in subparts[:4])
                sub_clauses.append(f"({and_expr})")

            seen_syns: list[str] = []
            for cand in [tok_lower, *subparts]:
                for s in _lookup_synonyms(cand):
                    if s != tok_lower and s not in subparts and s not in seen_syns:
                        seen_syns.append(s)
                    if len(seen_syns) >= 3:
                        break
                if len(seen_syns) >= 3:
                    break
            for s in seen_syns[:3]:
                sub_clauses.append(f'"{s.replace(chr(34), chr(34) * 2)}"*')

            if len(sub_clauses) > 1:
                clusters.append(f"({' OR '.join(sub_clauses)})")
            else:
                clusters.append(sub_clauses[0])
            continue

        synonyms = _lookup_synonyms(tok_lower)
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
    Retrieve active memories using FTS5 BM25 search or prioritized scoped fallback.

    - Prunes expired episodic memories first.
    - Enforces target-scope slot quota (>= ceil(limit * 0.6)) before global rules on pre-flight empty queries.
    - Clamps limit between 1 and 50.
    - Supports optional category filter ('rule', 'fact', 'preference', 'episodic').
    - Supports status_filter ('all' -> active & stale, 'active' -> active only, 'stale' -> stale only).
    - Increments hit_count and updates last_accessed for returned rows (except for administrative 'stale' audits).
    """
    if len(query) > 500:
        raise ValueError("Search query cannot exceed 500 characters.")

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
            clean_query = query.replace('"', " ").replace("\x00", " ")
            raw_tokens = re.findall(r"[\w.:-]+", clean_query, flags=re.UNICODE)
            stopwords = {
                "the", "is", "in", "to", "of", "for", "on", "with", "at", "by", "an", "be", "as",
            }
            clean_tokens: list[str] = []
            for tok in raw_tokens:
                t = tok.strip("-_.:*")
                if not t:
                    continue
                if t.upper() in ("AND", "OR", "NOT"):
                    continue
                if len(t) == 1 and not t.isdigit():
                    continue
                clean_tokens.append(t)

            if len(clean_tokens) > 1:
                filtered = [t for t in clean_tokens if t.lower() not in stopwords]
                if filtered:
                    clean_tokens = filtered

            if not clean_tokens and not re.search(r"\w", query):
                return []

            lexical_results: list[dict[str, Any]] = []
            fts_query = build_fts5_query(clean_tokens) if clean_tokens else ""
            if fts_query:
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
                        ORDER BY
                            (bm25(memories_fts, 5.0, 10.0, 1.0)
                             - CASE WHEN m.status = 'active' THEN 0.5 ELSE 0.0 END
                             - CASE m.category WHEN 'rule' THEN 0.3 WHEN 'fact' THEN 0.2 WHEN 'preference' THEN 0.1 ELSE 0.0 END),
                            m.hit_count DESC
                        LIMIT ?
                        """,
                        (*scopes, *cat_params, fts_query, limit),
                    ).fetchall()
                    lexical_results = [dict(r) for r in rows]
                except sqlite3.OperationalError as exc:
                    logger.warning("FTS5 MATCH query failed (%s): %s", exc, fts_query)
                    lexical_results = []

            if get_semantic_search_enabled():
                from src.semantic import reciprocal_rank_fusion, semantic_search_memories

                semantic_results = semantic_search_memories(
                    conn,
                    scopes,
                    query,
                    status_clause_m,
                    cat_clause_m,
                    cat_params,
                    limit=max(limit * 2, 16),
                )
                if semantic_results:
                    results = reciprocal_rank_fusion(lexical_results, semantic_results, limit=limit)
                else:
                    results = lexical_results
            else:
                results = lexical_results
        else:
            order_sql = """
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
            """
            if include_global and scope != "global":
                scope_rows = [
                    dict(r)
                    for r in conn.execute(
                        f"""
                        SELECT id, scope, category, subject, content, status, stale_reason, anchor_files, hit_count
                        FROM memories
                        WHERE scope = ?
                          AND {status_clause_bare}
                          AND valid_to IS NULL
                          {cat_clause_bare}
                        {order_sql}
                        """,
                        (scope, *cat_params, limit),
                    ).fetchall()
                ]
                global_rows = [
                    dict(r)
                    for r in conn.execute(
                        f"""
                        SELECT id, scope, category, subject, content, status, stale_reason, anchor_files, hit_count
                        FROM memories
                        WHERE scope = 'global'
                          AND {status_clause_bare}
                          AND valid_to IS NULL
                          {cat_clause_bare}
                        {order_sql}
                        """,
                        (*cat_params, limit),
                    ).fetchall()
                ]
                scope_quota = math.ceil(limit * 0.6)
                take_scope = min(len(scope_rows), max(scope_quota, limit - len(global_rows)))
                selected = list(scope_rows[:take_scope])
                remaining = limit - len(selected)
                if remaining > 0:
                    selected.extend(global_rows[:remaining])
                if len(selected) < limit and take_scope < len(scope_rows):
                    selected.extend(scope_rows[take_scope : take_scope + (limit - len(selected))])
                selected.sort(
                    key=lambda r: (
                        _CATEGORY_RANK.get(r["category"], 4),
                        0 if r["scope"] == scope else 1,
                        -r["hit_count"],
                        -r["id"],
                    )
                )
                for r in selected:
                    r.pop("hit_count", None)
                results = selected
            else:
                rows = conn.execute(
                    f"""
                    SELECT id, scope, category, subject, content, status, stale_reason, anchor_files
                    FROM memories
                    WHERE scope = ?
                      AND {status_clause_bare}
                      AND valid_to IS NULL
                      {cat_clause_bare}
                    {order_sql}
                    """,
                    (scope, *cat_params, limit),
                ).fetchall()
                results = [dict(r) for r in rows]

        if results and norm_status != "stale":
            ids = [r["id"] for r in results]
            id_str = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE memories SET hit_count = hit_count + 1, last_accessed = ? WHERE id IN ({id_str}) AND valid_to IS NULL",
                (ts, *ids),
            )

        return results
