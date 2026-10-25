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
| `manage_scope_alias(alias, canonical_scope, action)` | Manage dynamic project/folder aliases (`set`, `remove`, `list` with active/stale memory counts) or migrate/rename scopes (`rename`). |
| `manage_server_config(action, key, value)` | Inspect or update server configuration live at runtime (`list`, `set`, `reset`) with automatic token masking and security guardrails. |
| `manage_git_webhooks(action, repos, include_forks)` | Interactively manage Git push drift detection webhooks across Forgejo, Gitea, GitHub, or GitLab (`list`, `enable`, `disable`). |
| `get_client_setup_bundle(client, os_platform, instance_role, action)` | Retrieve client MCP JSON config, global directives (`GEMINI.md`), and `/remember` skill (`install_or_update`, `switch_role`, `uninstall`). |
| `export_bundle()` | Create a fresh online SQLite backup and package `helios_portable_bundle.tar.gz`. |

---

## Universal Webhook Provisioning & Drift Tracking

Helios tracks configuration drift automatically when commits touch memory `anchor_files`. To connect your Git repositories to Helios:

### 1. Conversational Agent Management (`manage_git_webhooks`)

Helios includes an interactive FastMCP tool so users and agents can audit and enable drift webhooks directly through chat:

- **List Repositories**: Ask your agent: *"List my Git repositories and check which ones have Helios drift tracking enabled."*
- **Enable Webhooks**: Ask your agent: *"Enable drift tracking on braz/helios and braz/homelab."*
- **Disable Webhooks**: Ask your agent: *"Disable drift tracking on braz/deprecated-service."*

To enable automated conversational management, configure your Git provider settings in `.env`:
```bash
HELIOS_GIT_PROVIDER=forgejo  # forgejo, gitea, github, gitlab
HELIOS_GIT_API_URL=https://git.example.com
HELIOS_GIT_TOKEN=your_personal_access_token
HELIOS_WEBHOOK_URL=https://helios.example.com/webhook/git
```

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

## Live Day-2 Configuration Management

Helios supports real-time Day-2 configuration updates directly through AI chat without container restarts:

### 1. Dynamic Server Configuration (`manage_server_config`)
- **Inspect Configuration**: Run `manage_server_config(action="list")` to view all configurable settings, active values, and their provenance (`db`, `env`, or `default`).
- **Live Overrides**: Modify settings on the fly with `manage_server_config(action="set", key="HELIOS_WORD_LIMIT", value="40")`. Changes persist in SQLite `runtime_settings` and take effect immediately without service restarts.
- **Reset Overrides**: Revert any runtime setting back to environment/default with `manage_server_config(action="reset", key="HELIOS_WORD_LIMIT")`.
- **Security Invariant**: Sensitive operational keys (`HELIOS_API_KEY`, `HELIOS_WEBHOOK_SECRET`, `MEMORY_DATA_DIR`, `HELIOS_ALLOWED_ORIGINS`) are strictly locked to environment variables and cannot be modified via DB or MCP tools. Secret tokens like `HELIOS_GIT_TOKEN` are automatically masked (`•••••••• (configured)`) in tool responses.

### 2. Client Lifecycle & Idempotent Directive Updates
- **Idempotent Delimiters**: Helios wraps all injected agent instructions between `<!-- HELIOS:START -->` and `<!-- HELIOS:END -->`. Agents can reconfigure or upgrade their directives without clobbering other custom instructions.
- **Role Switching**: Seamlessly change between `workstation` (desktop/IDE development) and `server-cli` (headless host management with token diet guardrails) using `get_client_setup_bundle(action="switch_role", instance_role="server-cli")`.
- **Clean Uninstallation**: To cleanly decouple an agent, run `get_client_setup_bundle(action="uninstall")` for exact removal steps of the MCP configuration block, directive markers, and the `/remember` skill.

---

## HTTP Endpoints

| Method & Path | Description |
| :--- | :--- |
| `GET /health` | Health check returning minimal status when unauthenticated, or full WAL/telemetry details when authenticated. |
| `GET /setup` | Returns self-contained AI-driven client setup prompt and non-destructive MCP config snippets. |
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

### 2. 1-Prompt AI Client Setup

Once Helios is deployed, connect any local or remote AI agent (Antigravity, Cursor, Claude Desktop, Claude Code) in seconds:

> **Paste this into your IDE or CLI agent on any machine:**
> ```text
> Fetch https://<your-helios-domain>/setup and configure my local MCP client, global directives, and /remember skill.
> ```

The agent will automatically detect the operating system, safely merge the `"helios"` configuration into its MCP configuration file without overwriting other servers, install the global directive (`GEMINI.md` / `CLAUDE.md`), and install the `/remember` skill.

Already connected agents can also run the FastMCP tool `get_client_setup_bundle()` at any time.

### 3. Local Development & Tests
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -q
```
