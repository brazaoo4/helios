"""
Seed baseline architecture rules, facts, and anchor files for Helios.

Execute via CLI:
    python -m src.seed
    python -m src.seed --scope global
    python -m src.seed --dry-run
    python -m src.seed --if-empty
    python -m src.seed --check

Or inside Docker:
    docker exec -it helios python -m src.seed
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from src.config import get_memory_data_dir, get_word_limit
from src.db import get_connection, init_db, resolve_scope, set_alias, upsert_memory
from src.exporter import sync_markdown_exports

INITIAL_FACTS = [
    # --- Global Architecture & Interaction Rules ---
    {
        "scope": "global",
        "category": "rule",
        "subject": "pre-flight-check",
        "content": "Always inspect docs/ARCHITECTURE.md as single source of truth before modifying stacks or networks.",
        "anchor_files": ["docs/ARCHITECTURE.md"],
    },
    {
        "scope": "global",
        "category": "rule",
        "subject": "docs-sync-mandate",
        "content": "Synchronously update docs/ARCHITECTURE.md and README.md whenever service or networking configs change.",
        "anchor_files": ["docs/ARCHITECTURE.md", "README.md"],
    },
    {
        "scope": "global",
        "category": "rule",
        "subject": "token-diet",
        "content": "Keep terminal command outputs concise; always use tail, silent flags, and grep.",
        "anchor_files": [],
    },
    {
        "scope": "global",
        "category": "rule",
        "subject": "code-generation",
        "content": "Output only modified blocks or unified diffs rather than entire redundant files.",
        "anchor_files": [],
    },

    # --- Helios Self-Knowledge ---
    {
        "scope": "helios",
        "category": "fact",
        "subject": "mcp-transport",
        "content": "Helios MCP exposes Streamable HTTP on /sse and /mcp, with legacy SSE fallback for older clients.",
        "anchor_files": ["src/server.py"],
    },
    {
        "scope": "helios",
        "category": "rule",
        "subject": "atomic-word-limit",
        "content": "AUDN Write Gate strictly enforces a <= 25-word limit per atomic memory fact.",
        "anchor_files": ["src/db.py"],
    },
    {
        "scope": "helios",
        "category": "fact",
        "subject": "storage-engine",
        "content": "Helios uses SQLite with WAL mode, busy_timeout=10000, and FTS5 BM25 search for sub-millisecond retrieval.",
        "anchor_files": ["src/db.py"],
    },
    {
        "scope": "helios",
        "category": "fact",
        "subject": "auto-markdown-export",
        "content": "Every memory mutation automatically syncs clean Markdown export summaries into the exports directory.",
        "anchor_files": ["src/exporter.py"],
    },
]


def validate_facts(facts: list[dict[str, Any]] | None = None) -> list[str]:
    """
    Validate a list of fact dictionaries against Helios memory invariants.
    Returns a list of human-readable error messages (empty if all valid).
    """
    items = INITIAL_FACTS if facts is None else facts
    errors = []
    valid_categories = {"rule", "fact", "preference", "episodic"}
    seen_slots: set[tuple[str, str]] = set()

    word_limit = get_word_limit()
    for idx, item in enumerate(items, 1):
        # 1. Required keys
        for key in ("scope", "category", "subject", "content", "anchor_files"):
            if key not in item:
                errors.append(f"Item #{idx}: missing required field '{key}'.")

        category = item.get("category", "")
        if category not in valid_categories:
            errors.append(f"Item #{idx}: invalid category '{category}'. Must be in {valid_categories}.")

        content = " ".join(item.get("content", "").strip().split())
        if not content:
            errors.append(f"Item #{idx}: content cannot be empty.")
        else:
            word_count = len(content.split())
            if word_count > word_limit:
                errors.append(
                    f"Item #{idx} ({item.get('scope')}/{item.get('subject')}): "
                    f"exceeds {word_limit}-word limit ({word_count} words): '{content}'"
                )

        anchors = item.get("anchor_files")
        if not isinstance(anchors, list):
            errors.append(f"Item #{idx}: anchor_files must be a list of file paths.")

        # Duplicate slot check (within this seed batch, using resolved canonical scope)
        raw_scope = item.get("scope", "").strip()
        scope = resolve_scope(raw_scope) if raw_scope else ""
        subj = item.get("subject", "").strip().lower()
        if scope and subj:
            slot = (scope, subj)
            if slot in seen_slots:
                errors.append(f"Item #{idx}: duplicate (scope, subject) slot '{scope}/{subj}' in seed list.")
            seen_slots.add(slot)

    return errors


def clear_memories(scope_filter: str | None = None) -> int:
    """
    Delete memories from the database.
    If scope_filter is provided, deletes only that resolved scope.
    Returns the count of deleted rows.
    """
    with get_connection() as conn:
        if scope_filter:
            target_scope = resolve_scope(scope_filter)
            cur = conn.execute("DELETE FROM memories WHERE scope = ?", (target_scope,))
        else:
            cur = conn.execute("DELETE FROM memories")
        return cur.rowcount


def is_db_empty() -> bool:
    """Check if the memories table currently contains zero active memories."""
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status = 'active' AND valid_to IS NULL"
        ).fetchone()[0]
        return count == 0


def seed(
    facts: list[dict[str, Any]] | None = None,
    scope_filter: str | None = None,
    dry_run: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """
    Populate baseline architecture rules and facts into Helios idempotently.

    Args:
        facts: Custom list of fact dictionaries (defaults to INITIAL_FACTS).
        scope_filter: If specified, only seed facts matching this raw or canonical scope.
        dry_run: If True, validate and simulate upsert without modifying SQLite or disk.
        verbose: If True, print live progress table to stdout.

    Returns:
        Structured result summary dict containing stats, actions, and exported files.
    """
    items = INITIAL_FACTS if facts is None else facts

    # 1. Validation check
    validation_errors = validate_facts(items)
    if validation_errors:
        err_msg = "\n  - " + "\n  - ".join(validation_errors)
        raise ValueError(f"Seed validation failed with {len(validation_errors)} error(s):{err_msg}")

    # 2. Filter by scope if requested
    target_scope = resolve_scope(scope_filter) if scope_filter else None
    if target_scope:
        items = [f for f in items if resolve_scope(f["scope"]) == target_scope]

    if not dry_run:
        init_db()

    if verbose:
        mode_str = " (DRY RUN - no writes)" if dry_run else ""
        scope_str = f" for scope '{target_scope}'" if target_scope else ""
        print(f"Populating knowledge base into Helios{mode_str}{scope_str} ({len(items)} facts)...")

    results = []
    action_counts = {"created": 0, "no-op": 0, "superseded": 0}

    for item in items:
        if dry_run:
            action = "simulated"
            mem_id = 0
            scope = resolve_scope(item["scope"])
            subj = item["subject"]
            action_counts["created"] += 1
            res = {"action": action, "id": mem_id, "scope": scope, "subject": subj}
        else:
            res = upsert_memory(
                raw_scope=item["scope"],
                category=item["category"],
                content=item["content"],
                subject=item["subject"],
                anchor_files=item["anchor_files"],
            )
            action = res["action"]
            mem_id = res["id"]
            scope = res["scope"]
            subj = item["subject"]

            if "created" in action:
                action_counts["created"] += 1
            elif "superseded" in action:
                action_counts["superseded"] += 1
            else:
                action_counts["no-op"] += 1

        results.append(res)
        if verbose:
            print(f"  [{action:<20}] #{mem_id:<3} ({scope}/{subj})")

    exported_files: list[str] = []
    if not dry_run:
        exported_files = sync_markdown_exports()
        if verbose:
            print(f"\nSeeding complete. Synced {len(exported_files)} Markdown export files:")
            for path in exported_files:
                print(f"  - {path}")

    summary = {
        "total_evaluated": len(items),
        "created": action_counts["created"],
        "no_op": action_counts["no-op"],
        "superseded": action_counts["superseded"],
        "exports": exported_files,
        "results": results,
    }
    return summary


def seed_if_empty(
    facts: list[dict[str, Any]] | None = None,
    verbose: bool = False,
) -> dict[str, Any] | None:
    """
    Seed baseline facts only if the active memories table is currently empty.
    Returns the seed summary dict if seeded, or None if already populated.
    """
    init_db()
    if is_db_empty():
        return seed(facts=facts, verbose=verbose)
    return None


def _parse_declarative_seed_file(seed_path: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """
    Parse a declarative seed file (.yaml, .yml, or .json).
    Supports either:
      - A top-level list of memory items: [ {scope, category, subject, content, anchor_files}, ... ]
      - A top-level dict with {"memories": [...], "aliases": {"alias": "canonical_scope"}}
    """
    raw_text = seed_path.read_text(encoding="utf-8")
    suffix = seed_path.suffix.lower()

    if suffix == ".json":
        parsed = json.loads(raw_text)
    elif suffix in (".yaml", ".yml"):
        try:
            import yaml
            parsed = yaml.safe_load(raw_text)
        except ImportError:
            parsed = json.loads(raw_text)
    else:
        raise ValueError(f"Unsupported seed file extension: {suffix}")

    if parsed is None:
        return [], {}
    if isinstance(parsed, list):
        return parsed, {}
    if isinstance(parsed, dict):
        memories = parsed.get("memories") or parsed.get("facts") or []
        aliases = parsed.get("aliases") or {}
        if not isinstance(memories, list):
            raise ValueError("'memories' in seed file must be a list.")
        if not isinstance(aliases, dict):
            raise ValueError("'aliases' in seed file must be a dictionary.")
        return memories, aliases
    raise ValueError("Seed file root must be a list of memories or a dict with 'memories'.")


def ingest_declarative_seed_files(data_dir: Path | None = None) -> int:
    """
    Declarative Seed File Ingestion:
    Checks if seed.yaml, seed.yml, or seed.json exists in MEMORY_DATA_DIR (/data).
    For each existing seed file:
      1. Parses items (and optional aliases).
      2. Calls upsert_memory for each valid item.
      3. Runs sync_markdown_exports().
      4. Atomically renames the file to seed.<ext>.imported (e.g. seed.yaml.imported).
    Returns the total number of memories ingested across all found seed files.
    """
    target_dir = data_dir if data_dir is not None else get_memory_data_dir()
    if not target_dir.exists():
        return 0

    init_db()
    total_ingested = 0

    for filename in ("seed.yaml", "seed.yml", "seed.json"):
        seed_file = target_dir / filename
        if not seed_file.is_file():
            continue

        try:
            items, aliases = _parse_declarative_seed_file(seed_file)
        except Exception:
            continue

        for alias_key, canonical_val in aliases.items():
            if isinstance(alias_key, str) and isinstance(canonical_val, str):
                try:
                    set_alias(alias_key, canonical_val)
                except ValueError:
                    pass

        ingested_in_file = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_scope = str(item.get("scope", "global"))
            category = str(item.get("category", "fact"))
            content = str(item.get("content", ""))
            subject = str(item.get("subject", ""))
            anchor_files = item.get("anchor_files")
            if not isinstance(anchor_files, list):
                anchor_files = []

            try:
                upsert_memory(
                    raw_scope=raw_scope,
                    category=category,
                    content=content,
                    subject=subject,
                    anchor_files=anchor_files,
                )
                ingested_in_file += 1
            except ValueError:
                # Skip invalid items so one bad entry doesn't crash startup
                continue

        sync_markdown_exports()
        imported_target = target_dir / f"{filename}.imported"
        os.replace(seed_file, imported_target)
        total_ingested += ingested_in_file

    return total_ingested


def main() -> None:
    """CLI Entrypoint supporting flags and arguments."""
    parser = argparse.ArgumentParser(
        description="Seed baseline architecture rules, facts, and anchor files for Helios.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scope",
        "-s",
        type=str,
        default=None,
        help="Filter seeding to a single canonical scope or alias (e.g. global, web, helios).",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Validate facts and simulate seeding without writing to the database or exports.",
    )
    parser.add_argument(
        "--check",
        "-c",
        action="store_true",
        help="Strictly validate all initial facts and exit with code 0 or 1.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe all memories (or targeted scope) before seeding.",
    )
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="Only seed if the database contains zero active memories.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON summary instead of plain text.",
    )

    args = parser.parse_args()

    # --check mode
    if args.check:
        errors = validate_facts(INITIAL_FACTS)
        if errors:
            print(f"Validation FAILED with {len(errors)} error(s):", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)
        print(f"Validation PASSED: {len(INITIAL_FACTS)} facts comply with all Helios constraints.")
        sys.exit(0)

    # --if-empty mode
    if args.if_empty:
        init_db()
        if not is_db_empty():
            if not args.json:
                print("Helios database is already populated. Skipping seeding (--if-empty).")
            else:
                print(json.dumps({"status": "skipped", "reason": "already_populated"}))
            sys.exit(0)

    # --reset mode
    if args.reset:
        init_db()
        deleted = clear_memories(scope_filter=args.scope)
        if not args.json:
            target = f"scope '{args.scope}'" if args.scope else "all scopes"
            print(f"Cleared {deleted} memory records from {target}.")

    try:
        summary = seed(
            facts=INITIAL_FACTS,
            scope_filter=args.scope,
            dry_run=args.dry_run,
            verbose=not args.json,
        )
        if args.json:
            print(json.dumps(summary, indent=2))
    except Exception as exc:
        print(f"Error during seeding: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()