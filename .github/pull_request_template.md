## Description

<!-- Provide a brief description of what this PR accomplishes and why it is needed. -->

## Type of Change

- [ ] `feat`: New feature or MCP tool
- [ ] `fix`: Bug fix
- [ ] `perf`: Performance improvement
- [ ] `docs`: Documentation updates
- [ ] `refactor`: Code refactoring without behavior change
- [ ] `test`: New or updated tests
- [ ] `chore`: Maintenance or CI adjustments

## Related Issue

<!-- Fixes #(issue) or Closes #(issue) -->

## Architectural Invariants Checklist

- [ ] **Token Budget**: Any new facts adhere to the `HELIOS_WORD_LIMIT` (<= 25 words default).
- [ ] **Event Loop Safety**: FastMCP synchronous file and database operations are offloaded via `anyio.to_thread.run_sync`.
- [ ] **SQLite Concurrency**: No nested `get_connection()` calls inside `BEGIN IMMEDIATE` transaction blocks.
- [ ] **Secret Redaction**: No sensitive tokens or secrets are exposed in logs, tool outputs, or `/setup` payloads.

## Verification Checklist

- [ ] `ruff check src/ tests/` passes with 0 errors.
- [ ] `pytest tests/ -v` passes with all tests green.
- [ ] `python -m src.seed --check` passes.
- [ ] Docker build succeeds (`docker build -t helios:test .`).
