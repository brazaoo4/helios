# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0.0 | :x:                |

## Reporting a Vulnerability

We take the security of Helios seriously. If you discover a vulnerability or potential security risk, please do **NOT** open a public issue.

Instead, report it via:
* **Email**: Send detailed findings to **brunobrazao4@gmail.com**.
* **GitHub Advisory**: Submit via [GitHub Private Vulnerability Reporting](https://github.com/brazaoo4/helios/security/advisories/new).

Please include:
1. Detailed description of the vulnerability.
2. Steps to reproduce or proof-of-concept payload.
3. Potential impact on confidential memories or host infrastructure.
4. Suggested remediation if available.

You will receive an acknowledgment within 48 hours and regular updates on triage and patching.

---

## Security Architecture & Built-In Safeguards

Helios is engineered with security-first invariants designed to protect private architecture context and prevent host compromise:

1. **Zero-Trust Auth Gate (`HELIOS_API_KEY`)**:
   - Constant-time verification (`hmac.compare_digest`) on all incoming requests to `/mcp`, `/sse`, and `/export/*`.
   - Healthcheck telemetry (`/health`) automatically redacts database sizes and memory statistics when unauthenticated.
2. **Fail-Closed Webhook Verification (`HELIOS_WEBHOOK_SECRET`)**:
   - Universal Git webhook endpoint (`POST /webhook/git`) validates HMAC-SHA256 signatures for GitHub, Forgejo, Gitea, and GitLab.
   - Enforces optional fail-closed rejection (`HELIOS_REQUIRE_WEBHOOK_SECRET=true`) returning `HTTP 503` if an endpoint is exposed without a secret.
3. **SSRF & Metadata Service Protection**:
   - Outbound requests (Git APIs, webhook registration) strictly validate URLs.
   - Blocks cloud metadata endpoints (`169.254.169.254`, `169.254.0.0/16`, `fe80::/10`, `metadata.google.internal`).
   - Blocks loopback addresses (`127.0.0.0/8`, `::1`, `localhost`) for external services, while allowing safe private LAN / Tailscale / container network routing.
4. **Credential Exfiltration Defense**:
   - If `HELIOS_GIT_API_URL` is changed at runtime, `HELIOS_GIT_TOKEN` cannot be exfiltrated to unauthorized domains.
5. **Streaming Denial-of-Service Protection**:
   - Webhook payloads are read via a bounded 1MB chunked stream. Payloads exceeding 1MB are aborted immediately with `HTTP 413 Payload Too Large` to prevent memory exhaustion.
6. **Least Privilege & Container Hardening**:
   - Container runs strictly rootless as unprivileged user `helios` (`uid=1000:gid=1000`).
   - Hardened with `cap_drop: ALL` and `no-new-privileges:true`.
   - Security-critical environment variables (`HELIOS_API_KEY`, `HELIOS_WEBHOOK_SECRET`, `MEMORY_DATA_DIR`) are immutable at runtime and cannot be overridden by MCP tools.
