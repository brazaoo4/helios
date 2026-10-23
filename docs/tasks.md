# Project Tasks: `helios` (Shared MCP Memory Server)

> **Goal:** Build and deploy **Helios**, a centralized, token-budgeted MCP memory server with SQLite FTS5 search, AUDN lifecycle management, Git-webhook drift detection, zero-trust ingress security, and dual-faced Markdown exports across IDE and CLI agents.

Milestone: `v1.0.0` · Plan: [technical-implementation-plan-mcp-shared-memory.md](technical-implementation-plan-mcp-shared-memory.md)

| Phase | Label | Blocked by |
| --- | --- | --- |
| 1 | `phase-1:setup` | — |
| 2 | `phase-2:db-engine` | Phase 1 |
| 3 | `phase-3:exporter` | Phase 2 |
| 4 | `phase-4:server` | Phases 2, 3 |
| 5 | `phase-5:docker-cicd` | Phase 4 |
| 6 | `phase-6:ingress` | Phase 5 |
| 7 | `phase-7:rollout` | Phase 6 |

---

## Phase 1: Repository & Local Python Setup
**Objective:** Initialize the repository and configure an isolated Python virtual environment (`venv`) for local development and testing.

- [x] **1.1 Clone the repository:**
  - `git clone https://git.example.com/org/helios.git && cd helios`
- [x] **1.2 Scaffold project structure:**
  - `mkdir -p src tests && touch src/__init__.py src/config.py src/db.py src/exporter.py src/server.py src/seed.py tests/__init__.py requirements.txt requirements-dev.txt Dockerfile .dockerignore .gitignore .agentignore README.md`
- [x] **1.3 Configure `.gitignore`, `.agentignore`, and `.dockerignore`:**
  - Add `.venv/`, `__pycache__/`, `*.pyc`, `data/`, `*.db`, `*.db-wal`, `*.db-shm`, `*.tar.gz`, `.env`, `.pytest_cache/` to `.gitignore` and `.agentignore`.
  - Add `.venv`, `data`, `.git`, `tests`, `.pytest_cache`, `*.md` to `.dockerignore`.
- [x] **1.4 Create `venv` & install dependencies:**
  - `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt`
- [x] **1.5 Verify SQLite FTS5 extension:**
  - `python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('create virtual table t using fts5(a)'); print(sqlite3.sqlite_version)"`

---

## Phase 2: Database Engine & AUDN Write Gate (`src/db.py`)
**Objective:** Build the SQLite storage layer with WAL concurrency, FTS5 search, dynamic scope aliases, deterministic supersession (AUDN), and Git-commit drift flagging.

- [x] **2.1 Connection & schema (`now_iso()`, `get_connection()`, `init_db()`):**
  - Resolve `MEMORY_DATA_DIR` dynamically via `src/config.py`.
  - Wrap connections in a `@contextlib.contextmanager` helper that commits on success, rolls back on exception, and always calls `conn.close()` in a `finally` block.
  - Set `timeout=10.0`, `PRAGMA journal_mode=WAL;`, `PRAGMA synchronous=NORMAL;`, `PRAGMA busy_timeout=10000;`, `PRAGMA wal_autocheckpoint=1000;`, `PRAGMA foreign_keys=ON;`.
- [x] **2.2 Dynamic scope normalization (`resolve_scope()`, `set_alias()`, `remove_alias()`, `list_aliases()`):**
  - Normalize paths (`/` and `\`), strip trailing slashes and `.git`, lowercase, and dynamically query `scope_aliases` in SQLite.
- [x] **2.3 TTL pruning (`prune_expired_episodic()`):**
  - Archive `episodic` memories untouched (`last_accessed`) for more than `HELIOS_EPISODIC_TTL_DAYS` (default 14 days) by setting `status='archived'` and `valid_to=now_iso()`.
- [x] **2.4 AUDN write gate (`upsert_memory()`):**
  - Validate `category` in `('rule', 'fact', 'preference', 'episodic')`.
  - Enforce non-empty `content` and configurable word limit (`HELIOS_WORD_LIMIT`, default $\le$ 25 words).
  - Execute writes inside `BEGIN IMMEDIATE` transactions.
  - Deduplicate exact active matches (`no-op`) and automatically supersede prior active records sharing `(scope, subject)` or `replaces_id`.
- [x] **2.5 FTS5 search (`query_memories()`):**
  - Sanitize user query strings safely and rank matches by `bm25(memories_fts), m.hit_count DESC`.
- [x] **2.6 Drift flagging (`flag_stale_by_files()`):**
  - Match `anchor_files` on exact path equality or `/` boundary suffix, marking affected memories as `stale`.
- [x] **2.7 Unit tests (`tests/test_db.py`):**
  - Verify schema, dynamic aliases, TTL pruning, configurable word limits, FTS5 search, and drift flagging.

---

## Phase 3: Markdown Exporter & Atomic Portable Bundle (`src/exporter.py`)
**Objective:** Mirror SQLite state into human-readable Markdown files and a crash-safe `.tar.gz` bundle.

- [x] **3.1 Active/stale Markdown renderer (`exports/<scope>.md`):**
  - Sanitize `scope` filenames and write atomically via `tempfile` + `os.replace()`.
- [x] **3.2 Historical changelog renderer (`exports/changelog/<scope>_history.md`):**
  - Render superseded/archived rows capped at `HELIOS_CHANGELOG_LIMIT` (default 100).
- [x] **3.3 Safe online backup & portable archive (`create_portable_archive()`):**
  - Use SQLite's `source_conn.backup(dest_conn)` API to snapshot the live WAL database before packaging `helios_portable_bundle.tar.gz`.
- [x] **3.4 Exporter unit tests (`tests/test_exporter.py`):**
  - Verify Markdown rendering, atomic writes, and `.tar.gz` snapshot integrity.

---

## Phase 4: FastMCP Server, Zero-Trust Auth & Universal Git Webhooks (`src/server.py`)
**Objective:** Expose MCP tools, zero-trust authentication middleware, redacted `/health`, and universal `/webhook/git` endpoints.

- [x] **4.1 FastMCP tools:**
  - `recall_memories`, `save_memory`, `deprecate_memory`, `recall_history`, `export_bundle`, and `manage_scope_alias`.
- [x] **4.2 Zero-Trust Security (`AuthGateMiddleware`):**
  - Enforce constant-time `hmac.compare_digest` verification against `Authorization: Bearer <key>` or `?token=<key>` when `HELIOS_API_KEY` is configured.
  - Redact database telemetry on `GET /health` for unauthenticated requests.
- [x] **4.3 Universal Git Webhook Adapter (`POST /webhook/git`):**
  - Support GitHub (`X-Hub-Signature-256`), Forgejo/Gitea (`X-Forgejo-Signature`), and GitLab (`X-Gitlab-Token`) push events.
- [x] **4.4 Server & webhook tests (`tests/test_server.py`):**
  - Verify MCP tools, `AuthGateMiddleware`, `/health` redaction, and multi-provider webhook verification.

---

## Phase 5: Containerization & Deployment Templates
**Objective:** Package Helios as a rootless Docker container (`helios`, `uid=1000:1000`) with clean open-source deployment templates.

- [x] **5.1 Multi-stage `Dockerfile`:**
  - Run as non-root user `helios` (`1000:1000`) on internal port `8000`.
- [x] **5.2 Sanitized deployment templates:**
  - Provide `docker-compose.example.yml`, `.env.example`, and `seed.example.yaml`.

---

## Phase 6: Reverse Proxy Ingress & Webhook Wiring
**Objective:** Expose Helios behind TLS reverse proxies and wire Git repository push webhooks.

- [x] **6.1 Configure Reverse Proxy (`helios.example.com`):**
  - Route HTTPS traffic to `http://helios:8000` with SSE/streaming support (`proxy_buffering off;`).
- [x] **6.2 Wire Repository Push Webhooks:**
  - Point GitHub, Forgejo/Gitea, or GitLab push webhooks to `https://helios.example.com/webhook/git` with `HELIOS_WEBHOOK_SECRET`.

---

## Phase 7: Declarative Knowledge Seeding & Rollout
**Objective:** Seed baseline facts via `/data/seed.yaml` and connect MCP clients.

- [x] **7.1 Declarative Startup Seeding (`src/seed.py`):**
  - Place `seed.yaml` or `seed.json` in `/data`; Helios ingests records on startup and renames the file to `seed.<ext>.imported`.
- [x] **7.2 Register Helios MCP in Client Configurations:**
  - Connect IDE and CLI agents to `https://helios.example.com/mcp` (or `/sse`).
