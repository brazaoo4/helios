# Changelog

All notable changes to this project will be documented in this file.
See [Conventional Commits](https://conventionalcommits.org) for commit guidelines.

## [1.0.0] - 2026-10-26

### Features

- **Engine**: Token-budgeted atomic memory engine enforcing AUDN (Add, Update, Deprecate, No-op) lifecycle semantics.
- **Storage**: Dual-plane storage architecture featuring sub-millisecond SQLite WAL with FTS5 BM25 search ranking, mirrored to human-readable Markdown exports.
- **Drift Detection**: Git-anchored drift detection via `POST /webhook/git` supporting GitHub, Forgejo, Gitea, and GitLab push events with automatic `[STALE]` flagging and 1MB chunked payload limits.
- **Client Onboarding**: 1-liner zero-secret setup scripts (`/setup.sh` and `/setup.ps1`) with auto-detection for Antigravity, Cursor, Claude Desktop, and Claude Code.
- **Day-2 Control Plane**: Conversational MCP tools for live server configuration (`manage_server_config`), alias migration (`manage_scope_alias`), Git webhooks management (`manage_git_webhooks`), and crash-safe backup archives (`export_bundle`).
- **Security**: Zero-trust constant-time API authentication (`HELIOS_API_KEY`), SSRF/cloud metadata blocking, loopback exfiltration guards, and rootless container execution (`uid=1000:gid=1000`).
