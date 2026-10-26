# Changelog

All notable changes to this project will be documented in this file.
See [Conventional Commits](https://conventionalcommits.org) for commit guidelines.

## [1.4.0](https://github.com/brazaoo4/helios/compare/v1.3.0...v1.4.0) (2026-10-26)


### Features

* conversational git webhooks, ai client setup, and day-2 live runtime config ([8731a15](https://github.com/brazaoo4/helios/commit/8731a1598c30716922dc8f4013b03e5bf2b0904f))
* Helios MCP memory engine with zero-trust security and multi-provider webhooks ([0d1cf81](https://github.com/brazaoo4/helios/commit/0d1cf81956a4891acff526c57373a97425e2dc5c))
* **onboarding:** bump to 1.2.0 and enforce write-through memory definition of done ([315a00f](https://github.com/brazaoo4/helios/commit/315a00f039993d609b2c48ee06759885c8713ed6))
* **onboarding:** include interactive git drift webhook audit as mandatory setup step ([b7d4b2f](https://github.com/brazaoo4/helios/commit/b7d4b2f3fc1c372b06c310651e13d09350c870c4))
* **oss:** prepare repository for public open-source release on GitHub ([d57e555](https://github.com/brazaoo4/helios/commit/d57e55503098485d0e6b2c28abf0cc5862baa8ac))
* scope migration, stale revalidation, rich schemas, and webhook sync ([0fa64f6](https://github.com/brazaoo4/helios/commit/0fa64f6ab4831296405931523f285c534b9f432f))
* **setup:** add /setup.ps1 and /setup.sh 1-liner automated onboarding endpoints ([af6c866](https://github.com/brazaoo4/helios/commit/af6c86667d577ef7bbab6cdd664a3528d4a593b7))


### Bug Fixes

* **ci:** simplify release-please extra-files to pyproject.toml and use dynamic __version__ ([95df038](https://github.com/brazaoo4/helios/commit/95df038bf193f8ec658e3d1893f44439a15ec0cc))
* **directives:** strengthen session memory maintenance wording to capture architecture and learnings ([8e8d270](https://github.com/brazaoo4/helios/commit/8e8d2708c25950a7d241d7d476c8dbbb91270c17))
* **onboarding:** escape double newline in bash setup template ([e7f01bf](https://github.com/brazaoo4/helios/commit/e7f01bf307570a49fa43f7c95673c70d41bf137d))
* **onboarding:** point Antigravity MCP config snippet to Streamable HTTP /mcp endpoint ([79ed9e7](https://github.com/brazaoo4/helios/commit/79ed9e7794a8e3bcbd8803e5b8c3c956acd6300c))
* pre-release audit remediation for security, concurrency, and client onboarding ([34742ea](https://github.com/brazaoo4/helios/commit/34742ea32ab1e0f23f7ff3f13c8327ebbe441eb6))
* **server:** convert AuthGateMiddleware to pure ASGI to prevent SSE streaming assertion crashes ([86f467b](https://github.com/brazaoo4/helios/commit/86f467bfd5a48a2f7452454441fc3f9ec418791d))


### Documentation

* remove reverse proxy configuration section from README ([368c446](https://github.com/brazaoo4/helios/commit/368c446d08e8a98263f4b668364c0c617e95870c))
* revamp README as public open-source landing page ([3348d01](https://github.com/brazaoo4/helios/commit/3348d0132115913e2d1eac99213a88627eab4d7f))
* rewrite comprehensive README with architecture diagram, tool schemas, and lifecycle workflows ([b71b801](https://github.com/brazaoo4/helios/commit/b71b801a1841a56c574f7550f4f928124958d645))
* upgrade Section 1 with self-hoster friendly compose.yaml and host notes ([16a5d2e](https://github.com/brazaoo4/helios/commit/16a5d2e625cf4672daf64778ee2be01887b3edff))

## [1.3.0](https://github.com/brazaoo4/helios/compare/v1.2.0...v1.3.0) (2026-10-26)


### Features

* conversational git webhooks, ai client setup, and day-2 live runtime config ([8731a15](https://github.com/brazaoo4/helios/commit/8731a1598c30716922dc8f4013b03e5bf2b0904f))
* Helios MCP memory engine with zero-trust security and multi-provider webhooks ([0d1cf81](https://github.com/brazaoo4/helios/commit/0d1cf81956a4891acff526c57373a97425e2dc5c))
* **onboarding:** bump to 1.2.0 and enforce write-through memory definition of done ([315a00f](https://github.com/brazaoo4/helios/commit/315a00f039993d609b2c48ee06759885c8713ed6))
* **onboarding:** include interactive git drift webhook audit as mandatory setup step ([b7d4b2f](https://github.com/brazaoo4/helios/commit/b7d4b2f3fc1c372b06c310651e13d09350c870c4))
* **oss:** prepare repository for public open-source release on GitHub ([d57e555](https://github.com/brazaoo4/helios/commit/d57e55503098485d0e6b2c28abf0cc5862baa8ac))
* scope migration, stale revalidation, rich schemas, and webhook sync ([0fa64f6](https://github.com/brazaoo4/helios/commit/0fa64f6ab4831296405931523f285c534b9f432f))
* **setup:** add /setup.ps1 and /setup.sh 1-liner automated onboarding endpoints ([af6c866](https://github.com/brazaoo4/helios/commit/af6c86667d577ef7bbab6cdd664a3528d4a593b7))


### Bug Fixes

* **ci:** simplify release-please extra-files to pyproject.toml and use dynamic __version__ ([95df038](https://github.com/brazaoo4/helios/commit/95df038bf193f8ec658e3d1893f44439a15ec0cc))
* **directives:** strengthen session memory maintenance wording to capture architecture and learnings ([8e8d270](https://github.com/brazaoo4/helios/commit/8e8d2708c25950a7d241d7d476c8dbbb91270c17))
* **onboarding:** point Antigravity MCP config snippet to Streamable HTTP /mcp endpoint ([79ed9e7](https://github.com/brazaoo4/helios/commit/79ed9e7794a8e3bcbd8803e5b8c3c956acd6300c))
* pre-release audit remediation for security, concurrency, and client onboarding ([34742ea](https://github.com/brazaoo4/helios/commit/34742ea32ab1e0f23f7ff3f13c8327ebbe441eb6))


### Documentation

* remove reverse proxy configuration section from README ([368c446](https://github.com/brazaoo4/helios/commit/368c446d08e8a98263f4b668364c0c617e95870c))
* revamp README as public open-source landing page ([3348d01](https://github.com/brazaoo4/helios/commit/3348d0132115913e2d1eac99213a88627eab4d7f))
* rewrite comprehensive README with architecture diagram, tool schemas, and lifecycle workflows ([b71b801](https://github.com/brazaoo4/helios/commit/b71b801a1841a56c574f7550f4f928124958d645))
* upgrade Section 1 with self-hoster friendly compose.yaml and host notes ([16a5d2e](https://github.com/brazaoo4/helios/commit/16a5d2e625cf4672daf64778ee2be01887b3edff))

## [1.2.0] - 2026-10-26

### Features

- **Onboarding**: Enforce Write-Through Definition of Done (DoD) in global client directives (`GEMINI.md`, `CLAUDE.md`, `.cursor/rules/helios.mdc`) and `/remember` skill across all supported environments.

## [1.0.0] - 2026-10-26

### Features

- **Engine**: Token-budgeted atomic memory engine enforcing AUDN (Add, Update, Deprecate, No-op) lifecycle semantics.
- **Storage**: Dual-plane storage architecture featuring sub-millisecond SQLite WAL with FTS5 BM25 search ranking, mirrored to human-readable Markdown exports.
- **Drift Detection**: Git-anchored drift detection via `POST /webhook/git` supporting GitHub, Forgejo, Gitea, and GitLab push events with automatic `[STALE]` flagging and 1MB chunked payload limits.
- **Client Onboarding**: 1-liner zero-secret setup scripts (`/setup.sh` and `/setup.ps1`) with auto-detection for Antigravity, Cursor, Claude Desktop, and Claude Code.
- **Day-2 Control Plane**: Conversational MCP tools for live server configuration (`manage_server_config`), alias migration (`manage_scope_alias`), Git webhooks management (`manage_git_webhooks`), and crash-safe backup archives (`export_bundle`).
- **Security**: Zero-trust constant-time API authentication (`HELIOS_API_KEY`), SSRF/cloud metadata blocking, loopback exfiltration guards, and rootless container execution (`uid=1000:gid=1000`).
