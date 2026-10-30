# Changelog

All notable changes to this project will be documented in this file.
See [Conventional Commits](https://conventionalcommits.org) for commit guidelines.

## [1.7.4](https://github.com/brazaoo4/helios/compare/v1.7.3...v1.7.4) (2026-10-30)


### Documentation

* add system architecture specification and update repository layout docs ([8931429](https://github.com/brazaoo4/helios/commit/89314297ee2cc1b9836eab81b9967023b96a46ea))
* add system architecture specification and update repository layout docs ([73614e9](https://github.com/brazaoo4/helios/commit/73614e98df79e29d9a5996b3029e923529a94803))

## [1.7.3](https://github.com/brazaoo4/helios/compare/v1.7.2...v1.7.3) (2026-10-30)


### Bug Fixes

* **mcp:** add explicit ToolAnnotations and remove onboarding env false-positives ([0335b15](https://github.com/brazaoo4/helios/commit/0335b151aa87ebb825ce76c1838e42916d7d5070))
* **mcp:** add explicit ToolAnnotations and remove onboarding env false-positives ([1446bee](https://github.com/brazaoo4/helios/commit/1446beed72c1246d5e0e7f655a2692518d498a5c))

## [1.7.2](https://github.com/brazaoo4/helios/compare/v1.7.1...v1.7.2) (2026-10-28)


### Documentation

* remove social banner from README ([ea51b6c](https://github.com/brazaoo4/helios/commit/ea51b6ce439f94004741d473d4bf3cc37791a37d))
* remove social banner from README ([462a197](https://github.com/brazaoo4/helios/commit/462a19768fc9f8868abec0ea99edb05a8b87638c))

## [1.7.1](https://github.com/brazaoo4/helios/compare/v1.7.0...v1.7.1) (2026-10-28)


### Documentation

* add social preview banner and embed in README ([209acbe](https://github.com/brazaoo4/helios/commit/209acbe002ccbc41a9a9a99b8d0dc5cbbde56593))
* reframe README intro with personal project narrative ([4e15926](https://github.com/brazaoo4/helios/commit/4e15926834bc62c553bfec26165bc92e5cc5de3a))

## [1.7.0](https://github.com/brazaoo4/helios/compare/v1.6.0...v1.7.0) (2026-10-28)


### Features

* conversational git webhooks, ai client setup, and day-2 live runtime config ([8731a15](https://github.com/brazaoo4/helios/commit/8731a1598c30716922dc8f4013b03e5bf2b0904f))
* Helios MCP memory engine with zero-trust security and multi-provider webhooks ([0d1cf81](https://github.com/brazaoo4/helios/commit/0d1cf81956a4891acff526c57373a97425e2dc5c))
* **onboarding:** add 8-client ecosystem support and server-driven directive drift detection ([90ee80d](https://github.com/brazaoo4/helios/commit/90ee80d70e92d3dedbe3df98e9bc15df2e1e259d))
* **onboarding:** add client uninstaller endpoints and conversational removal support ([3d9c4d4](https://github.com/brazaoo4/helios/commit/3d9c4d4335fd2808fa3dd35c2c9d904ca9b8de2f))
* **onboarding:** add terminal token diet and noise suppression directives ([0cc82cf](https://github.com/brazaoo4/helios/commit/0cc82cff38bc95d9bb28b0f780d1db8c7b2ec418))
* **onboarding:** bump to 1.2.0 and enforce write-through memory definition of done ([315a00f](https://github.com/brazaoo4/helios/commit/315a00f039993d609b2c48ee06759885c8713ed6))
* **onboarding:** include interactive git drift webhook audit as mandatory setup step ([b7d4b2f](https://github.com/brazaoo4/helios/commit/b7d4b2f3fc1c372b06c310651e13d09350c870c4))
* **onboarding:** include pre-invocation write-through guard hook in setup script ([9e5459b](https://github.com/brazaoo4/helios/commit/9e5459bde047c793e654e28e4d9e678aa5525862))
* **oss:** prepare repository for public open-source release on GitHub ([d57e555](https://github.com/brazaoo4/helios/commit/d57e55503098485d0e6b2c28abf0cc5862baa8ac))
* **release:** trigger 1.7.0 release ([c8e0db6](https://github.com/brazaoo4/helios/commit/c8e0db62ad820d0bb49f7fde420b5c97203a4ca5))
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

## [1.6.0](https://github.com/brazaoo4/helios/compare/v1.5.0...v1.6.0) (2026-10-28)


### Features

* **onboarding:** add 8-client ecosystem support and server-driven directive drift detection ([90ee80d](https://github.com/brazaoo4/helios/commit/90ee80d70e92d3dedbe3df98e9bc15df2e1e259d))
* **onboarding:** add client uninstaller endpoints and conversational removal support ([3d9c4d4](https://github.com/brazaoo4/helios/commit/3d9c4d4335fd2808fa3dd35c2c9d904ca9b8de2f))

## [1.5.0](https://github.com/brazaoo4/helios/compare/v1.4.0...v1.5.0) (2026-10-27)


### Features

* **onboarding:** add terminal token diet and noise suppression directives ([0cc82cf](https://github.com/brazaoo4/helios/commit/0cc82cff38bc95d9bb28b0f780d1db8c7b2ec418))


## [1.4.0](https://github.com/brazaoo4/helios/compare/v1.3.0...v1.4.0) (2026-10-27)


### Features

* conversational git webhooks, ai client setup, and day-2 live runtime config ([8731a15](https://github.com/brazaoo4/helios/commit/8731a1598c30716922dc8f4013b03e5bf2b0904f))
* Helios MCP memory engine with zero-trust security and multi-provider webhooks ([0d1cf81](https://github.com/brazaoo4/helios/commit/0d1cf81956a4891acff526c57373a97425e2dc5c))
* **onboarding:** add terminal token diet and noise suppression directives ([0cc82cf](https://github.com/brazaoo4/helios/commit/0cc82cff38bc95d9bb28b0f780d1db8c7b2ec418))
* **onboarding:** bump to 1.2.0 and enforce write-through memory definition of done ([315a00f](https://github.com/brazaoo4/helios/commit/315a00f039993d609b2c48ee06759885c8713ed6))
* **onboarding:** include interactive git drift webhook audit as mandatory setup step ([b7d4b2f](https://github.com/brazaoo4/helios/commit/b7d4b2f3fc1c372b06c310651e13d09350c870c4))
* **onboarding:** include pre-invocation write-through guard hook in setup script ([9e5459b](https://github.com/brazaoo4/helios/commit/9e5459bde047c793e654e28e4d9e678aa5525862))
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
