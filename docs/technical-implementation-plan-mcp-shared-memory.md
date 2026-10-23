# Technical Implementation Plan: `helios` (Centralized Agent Memory Engine)

> **Target Deployment:** Docker Compose / Containerized Linux Host (`uid=1000:1000`)
> **Clients:** IDE & CLI AI Coding Agents across Linux, macOS, and Windows
> **Protocol:** Model Context Protocol (Streamable HTTP `/mcp` & SSE `/sse`)

---

## 1. Architecture & Protocol Mechanics

Helios provides a persistent, shared memory layer across AI coding agent instances without creating token bloat or cloud lock-in.

```text
  [IDE Agent]              [CLI Agent]              [Remote Agent]
       │                        │                         │
       └────────────────────────┼─────────────────────────┘
                                │ HTTPS / Streamable HTTP & SSE
                                ▼
       ┌──────────────────────────────────────────────────┐
       │        Reverse Proxy (helios.example.com)        │
       │        - TLS Termination (Let's Encrypt)         │
       └────────────────────────┬─────────────────────────┘
                                │
                                ▼
       ┌──────────────────────────────────────────────────┐
       │          helios Container (Port 8000)            │
       │  ┌────────────────────────────────────────────┐  │
       │  │ FastMCP ("Helios") + Starlette Engine      │  │
       │  │ - Zero-Trust AuthGateMiddleware            │  │
       │  │ - Token-budgeted Tools (<= 25 words/fact)  │  │
       │  │ - Universal Git Webhook (/webhook/git)     │  │
       │  └─────────────────────┬──────────────────────┘  │
       └────────────────────────┼─────────────────────────┘
                                │ /data volume mount
                                ▼
       ┌──────────────────────────────────────────────────┐
       │               Persistent Data Volume             │
       │  ┌───────────────────────┐ ┌──────────────────┐  │
       │  │  SQLite (WAL + FTS5)  │ │ Markdown Exports │  │
       │  │  - Safe Concurrency   │ │ - exports/*.md   │  │
       │  │  - AUDN Write Gate    │ │ - changelog/*.md │  │
       │  │  - Online Backup API  │ │ - .tar.gz bundle │  │
       │  └───────────────────────┘ └──────────────────┘  │
       └──────────────────────────────────────────────────┘
```

### Core Architecture Decisions

1. **Zero-Trust Ingress (`AuthGateMiddleware`)**:
   When `HELIOS_API_KEY` is unset, Helios runs in open local/mesh mode. When set, `AuthGateMiddleware` enforces constant-time (`hmac.compare_digest`) verification against `Authorization: Bearer <key>` or `?token=<key>` query parameters, while keeping `GET /health` (with redacted telemetry) and `POST /webhook/*` accessible.
2. **Crash-Safe SQLite Resource Management**:
   Helios uses an explicit `@contextlib.contextmanager` wrapper that enables `WAL` mode, commits on success, rolls back on error, and unconditionally calls `conn.close()` in a `finally` block.
3. **Safe Online Backup Snapshots**:
   Archiving active SQLite Write-Ahead Log (`WAL`) databases using raw filesystem `tar` commands can capture half-written pages. Helios uses SQLite’s online backup API (`src_conn.backup(dest_conn)`) to create a consolidated snapshot before building `.tar.gz` export bundles.
4. **Universal Git Webhook Drift Detection**:
   `POST /webhook/git` auto-detects GitHub (`X-Hub-Signature-256`), Forgejo/Gitea (`X-Forgejo-Signature` / `X-Gitea-Signature`), and GitLab (`X-Gitlab-Token`), flagging anchored memories as `[STALE]` whenever their referenced files change in a push commit.

---

## 2. Repository Structure

```text
helios/
├── src/
│   ├── __init__.py          # Package marker
│   ├── config.py            # Dynamic environment configuration and bounds validation
│   ├── db.py                # SQLite schema, WAL, FTS5 BM25, dynamic aliases, and AUDN gate
│   ├── exporter.py          # Atomic Markdown renderer and online SQLite backup archiver
│   ├── seed.py              # Declarative seed file ingestion and CLI seeder
│   └── server.py            # FastMCP tools, AuthGateMiddleware, /health, and /webhook/git
├── tests/
│   ├── __init__.py
│   ├── test_db.py           # Unit tests for config, SQLite, aliases, FTS5, and drift
│   ├── test_exporter.py     # Unit tests for Markdown output and .tar.gz integrity
│   ├── test_seed.py         # Unit tests for seed validation and declarative ingestion
│   └── test_server.py       # Integration tests for MCP tools, auth gate, and webhooks
├── .env.example             # Documented environment variables template
├── docker-compose.example.yml
├── seed.example.yaml        # Example declarative baseline seed file
├── Dockerfile               # Rootless container running as uid=1000:1000 (helios)
├── README.md
├── requirements.txt
└── requirements-dev.txt
```

---

## 3. Environment Configuration (`src/config.py`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `MEMORY_DATA_DIR` | `/data` | Directory storing `memory.db`, `exports/`, and portable bundles. |
| `HELIOS_API_KEY` | `None` | Optional Bearer/query token enabling zero-trust authentication. |
| `HELIOS_WEBHOOK_SECRET` | `None` | Shared secret for verifying GitHub, Forgejo/Gitea, or GitLab webhooks. |
| `HELIOS_WORD_LIMIT` | `25` | Maximum words allowed per atomic memory fact. |
| `HELIOS_EPISODIC_TTL_DAYS` | `14` | Inactivity TTL (in days) before `episodic` memories are archived. |
| `HELIOS_CHANGELOG_LIMIT` | `100` | Maximum historical records written per scope changelog file. |
| `HELIOS_ALLOWED_ORIGINS` | `*` | Comma-separated list of allowed CORS origins. |

---

## 4. Verification & Operational Runbook

### 1. Run Automated Test Suite
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

### 2. Declarative Seeding
Copy `seed.example.yaml` to `/data/seed.yaml` before starting the container. On startup, Helios ingests all aliases and memories, generates Markdown exports in `/data/exports/`, and renames the file to `/data/seed.yaml.imported`.

### 3. Health & Telemetry Check
```bash
# Unauthenticated (minimal status when HELIOS_API_KEY is set)
curl -i https://helios.example.com/health

# Authenticated (full WAL and active memory telemetry)
curl -i -H "Authorization: Bearer $HELIOS_API_KEY" https://helios.example.com/health
```
