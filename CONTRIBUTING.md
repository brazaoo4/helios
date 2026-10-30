# Contributing to Helios

Thank you for your interest in contributing to **Helios**!

Helios is a token-budgeted, drift-aware MCP memory engine designed to keep AI coding agents grounded and aligned across long software projects.

---

## 🛠️ Development Setup

### Prerequisites

* Python 3.12+ (or 3.13 / 3.14)
* SQLite 3.35+ (with FTS5 support, standard in modern Python distributions)
* Docker & Docker Compose (for container testing)

### Local Environment Setup

```bash
# Clone the repository
git clone https://github.com/brazaoo4/helios.git
cd helios

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1

# Install runtime and development dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run the test suite and verify invariants
ruff check src/ tests/
pytest tests/ -v
python -m src.seed --check
```

---

## 📂 Repository Layout & Packaging

Helios follows a modular enterprise architecture. Detailed technical design is documented in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**:

```text
src/
├── server.py              # Composition root (< 130 lines) assembling ASGI app & re-exports
├── middleware/            # Security (AuthGate), transport (Hybrid / SSE), and lifespan
├── routes/                # Starlette HTTP REST routes (health, setup, exports, git_webhooks)
├── tools/                 # FastMCP tools (base, memory, config, admin)
├── config.py              # Layered settings engine (SQLite > Env > Defaults)
├── db/                    # Modular SQLite database engine (connection, schema, scopes, memories, search, drift, audit)
├── exporter.py            # Markdown mirror synchronization & backup archive generation
├── onboarding/            # Script generation, multi-client setup runbooks, and uninstallation
├── webhooks.py            # Git provider integrations (GitHub, Forgejo/Gitea, GitLab)
└── seed.py                # Declarative seed validator & ingestion runner

tests/
├── conftest.py            # Shared environment & database isolation fixtures
├── middleware/            # Tests for AuthGate and transport multiplexing
├── routes/                # Tests for REST routes, health telemetry, setup, and webhooks
├── tools/                 # Tests for FastMCP tools, schemas, and thread offloading
└── onboarding/            # Tests for client config, templates, bundles, and scripts
```

---

## 📐 Architectural Guardrails for Contributors

When modifying Helios, you must adhere to the following core invariants:

1. **Non-Blocking FastMCP Execution**:
   - Never block Starlette's main `asyncio` event loop.
   - Any database transactions, disk file I/O (e.g. Markdown exports), or archive creation must be dispatched via `anyio.to_thread.run_sync`.
2. **SQLite Locking & Transaction Discipline**:
   - Never nest `get_connection()` calls inside an active `BEGIN IMMEDIATE` transaction block.
   - Always rely on the single-writer SQLite WAL model (`busy_timeout=10000`).
3. **Atomic Memory Word Budget (AUDN)**:
   - Fact content submitted to `save_memory` must not exceed `HELIOS_WORD_LIMIT` (default 25 words).
   - Reject verbose text with clear guidance to keep agent context high-density.
4. **Secret Redaction**:
   - Never output `HELIOS_API_KEY`, `HELIOS_GIT_TOKEN`, or webhook secrets in `/setup` outputs, logs, or error responses.
5. **Thread-Safe Markdown Sync**:
   - All disk export updates must acquire `_EXPORT_LOCK` to prevent interleaving writes.

---

## 📝 Commit Conventions (Release Please)

This repository uses **[Conventional Commits](https://www.conventionalcommits.org/)** to drive automated semantic versioning and release notes via **Google Release Please**:

| Prefix | Semantic Version Bump | Usage |
| :--- | :--- | :--- |
| `feat:` | **Minor** (`0.1.0` → `0.2.0`) | New feature, MCP tool, or client capability. |
| `fix:` | **Patch** (`0.1.0` → `0.1.1`) | Bug fix or error handling improvement. |
| `perf:` | **Patch** | Performance optimization (caching, query speed). |
| `docs:` | None (or patch if configured) | Documentation or README updates. |
| `refactor:` | None (or patch if configured) | Code refactoring without behavior changes. |
| `test:` | None | Adding or correcting tests. |
| `chore:` | None | Dependency maintenance, CI tweaks. |

> [!TIP]
> Breaking changes should append `!` after the prefix (e.g. `feat!: change default port to 8080`) or include `BREAKING CHANGE:` in the commit footer to trigger a **Major** version bump.

---

## 🚀 Pull Request Guidelines

1. Branch off `main` (or `master`): `git checkout -b feat/my-new-feature`.
2. Write clean code and accompanying unit tests under `tests/`.
3. Verify that all checks pass:
   ```bash
   ruff check src/ tests/
   pytest tests/ -v
   python -m src.seed --check
   ```
4. Push your branch and open a Pull Request against `main`. Fill in the PR template thoroughly.
