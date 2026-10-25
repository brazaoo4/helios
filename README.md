# Helios — Centralized MCP Memory Server

**Helios** is a token-budgeted Model Context Protocol (MCP) shared memory engine built for AI coding agents across IDEs, CLIs, local networks, and public cloud deployments.

It provides sub-millisecond full-text retrieval via **SQLite FTS5 (BM25)**, deterministic **AUDN (Add / Update / Deprecate / No-op)** lifecycle gates, **universal Git webhook drift detection** (GitHub, Forgejo/Gitea, GitLab), **zero-trust authentication**, and dual-faced **Markdown + portable `.tar.gz` exports**.

---

## Architecture & Key Features

- **Centralized Runtime Configuration (`src/config.py`)**:
  - Dynamic environment resolution for `MEMORY_DATA_DIR`, `HELIOS_API_KEY`, `HELIOS_WEBHOOK_SECRET`, `HELIOS_WORD_LIMIT` (default `25`), `HELIOS_EPISODIC_TTL_DAYS` (default `14`), `HELIOS_CHANGELOG_LIMIT` (default `100`), and `HELIOS_ALLOWED_ORIGINS` (default `*`).
- **Storage Engine (`src/db.py`)**:
  - SQLite with `journal_mode=WAL`, `busy_timeout=10000`, `synchronous=NORMAL`, and `foreign_keys=ON`.
  - Virtual FTS5 table (`memories_fts`) synchronized via `AFTER INSERT`, `AFTER DELETE`, and column-scoped `AFTER UPDATE OF scope, subject, content` triggers.
  - Configurable TTL archival for `episodic` memories (`prune_expired_episodic()`).
  - Dynamic scope normalization (`resolve_scope()`) querying SQLite `scope_aliases` at runtime and falling back to normalized repository/directory names.
- **AUDN Write Gate (`upsert_memory()`)**:
  - Enforces a configurable word limit (`HELIOS_WORD_LIMIT`, default $\le$ 25 words) per memory to prevent LLM context bloat.
  - Prevents write collisions with `BEGIN IMMEDIATE` transactions.
  - Deduplicates identical active memories (`no-op`), and automatically supersedes older active memories sharing the same `(scope, subject)` slot or explicit `replaces_id`.
- **Zero-Trust Security & Public Ingress Hardening (`src/server.py`)**:
  - `AuthGateMiddleware` enforces constant-time `hmac.compare_digest` verification against `Authorization: Bearer <key>` or `?token=<key>` when `HELIOS_API_KEY` is configured, while supporting open mode when unset.
  - Redacts `GET /health` database telemetry for unauthenticated callers when `HELIOS_API_KEY` is enabled.
- **Declarative Seeding & Cold-Start Onboarding (`src/seed.py`)**:
  - Automatically ingests `/data/seed.yaml` or `/data/seed.json` on startup, syncs Markdown exports, and atomically renames the file to `seed.<ext>.imported`.
  - Emits a cold-start onboarding prompt in `recall_memories` when the database contains zero active memories.

---

## MCP Tools

| Tool | Description |
| :--- | :--- |
| `recall_memories(scope, query, category, status_filter, limit, include_global)` | Search active/stale memories in `<scope>` (plus `global`) using FTS5 BM25 ranking or categorical priority (`rule` $\rightarrow$ `fact` $\rightarrow$ `preference` $\rightarrow$ `episodic`). Supports filtering by category (`rule`, `fact`, `preference`, `episodic`) and status (`all`, `active`, `stale`). |
| `save_memory(scope, category, content, subject, anchor_files, replaces_id)` | Create or supersede an atomic memory ($\le$ `HELIOS_WORD_LIMIT` words) and sync Markdown exports. |
| `revalidate_memories(memory_ids)` | Batch revalidate stale memories back to `active` status after inspecting modified `anchor_files`. |
| `deprecate_memory(memory_id, reason)` | Archive an obsolete memory and log it to the scope changelog. |
| `recall_history(scope, limit)` | Inspect superseded and archived memories for time-travel debugging and audit history. |
| `manage_scope_alias(alias, canonical_scope, action)` | Manage dynamic project/folder aliases (`set`, `remove`, `list`) or migrate/rename scopes (`rename`). |
| `export_bundle()` | Create a fresh online SQLite backup and package `helios_portable_bundle.tar.gz`. |

---

## Universal Webhook Provisioning & Drift Tracking

Helios tracks configuration drift automatically when commits touch memory `anchor_files`. To connect your Git repositories to Helios:

### 1. Backfilling Existing Repositories (`scripts/sync_webhooks.py`)

A standalone, provider-agnostic CLI script is included to inspect all existing repositories and idempotently register push webhooks (`POST /webhook/git` with JSON payload and HMAC secret):

```bash
# Forgejo / Gitea
python scripts/sync_webhooks.py \
  --provider forgejo \
  --api-url https://git.example.com \
  --token "$GIT_API_TOKEN" \
  --webhook-url https://helios.example.com/webhook/git \
  --webhook-secret "$HELIOS_WEBHOOK_SECRET"

# GitHub
python scripts/sync_webhooks.py \
  --provider github \
  --token "$GITHUB_TOKEN" \
  --owner my-org \
  --webhook-url https://helios.example.com/webhook/git \
  --webhook-secret "$HELIOS_WEBHOOK_SECRET"
```

Environment variables `GIT_API_URL`, `GIT_API_TOKEN`, `GIT_OWNER`, `HELIOS_WEBHOOK_URL`, and `HELIOS_WEBHOOK_SECRET` are read automatically if flags are omitted.

### 2. Zero-Script Setup for New Repositories (Default & Org Webhooks)

To automatically provision Helios drift webhooks on all future repositories without running scripts:

- **Forgejo / Gitea Default Webhook**:
  1. Navigate to **Site Administration** $\rightarrow$ **Default Webhooks** (`/admin/hooks`).
  2. Click **Add Webhook** $\rightarrow$ **Gitea** (or Forgejo).
  3. Set **Target URL** to `https://<helios-host>/webhook/git`.
  4. Set **HTTP Method** to `POST` and **Content Type** to `application/json`.
  5. Fill in the **Secret** matching `HELIOS_WEBHOOK_SECRET`.
  6. Under **Trigger On**, select **Push Events**.
  7. Save. Every newly created repository on your Git server automatically inherits this webhook.

- **GitHub Organization Webhook**:
  1. Navigate to your Organization $\rightarrow$ **Settings** $\rightarrow$ **Webhooks** (`https://github.com/organizations/<org>/settings/hooks`).
  2. Click **Add webhook**.
  3. Set **Payload URL** to `https://<helios-host>/webhook/git`.
  4. Set **Content type** to `application/json`.
  5. Enter the **Secret** matching `HELIOS_WEBHOOK_SECRET`.
  6. Under events, select **Just the push event**.
  7. Save. All current and future repositories in the organization trigger drift evaluation on push.

---

## HTTP Endpoints

| Method & Path | Description |
| :--- | :--- |
| `GET /health` | Health check returning minimal status when unauthenticated, or full WAL/telemetry details when authenticated. |
| `GET /export/markdown` | Lists generated Markdown scope export files and sizes. |
| `GET /export/bundle` | Generates and downloads `helios_portable_bundle.tar.gz`. |
| `POST /webhook/git`<br>`POST /webhook/forgejo`<br>`POST /hooks/git-commit` | Universal Git `push` webhook receiver (GitHub `X-Hub-Signature-256`, Forgejo/Gitea `X-Forgejo-Signature`, GitLab `X-Gitlab-Token`) for `anchor_files` drift detection. |
| `/mcp` & `/sse` | MCP Streamable HTTP and SSE endpoints. |

---

## Quick Start & Deployment

### 1. Docker Compose Deployment
```bash
cp .env.example .env
cp docker-compose.example.yml docker-compose.yml
mkdir -p data
cp seed.example.yaml data/seed.yaml
docker compose up -d --build
```

### 2. Local Development & Tests
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -q
```
