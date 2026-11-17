"""Programmatic AUDN secret firewall, injection-marker blocker, and log/error redaction."""

import re

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<!--\s*helios:", re.IGNORECASE),
    re.compile(r"</?\s*helios_memories\b", re.IGNORECASE),
    re.compile(r"\[\s*client\s+directive\s+drift", re.IGNORECASE),
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,255}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9\-=_]{20,}\b"),
    re.compile(r"\bsk-(?:proj-|ant-|live-|test-)?[A-Za-z0-9\-_]{20,}\b"),
    re.compile(r"\bAIzaSy[A-Za-z0-9\-_]{33}\b"),
    re.compile(r"\btskey-(?:auth|api|client)-[A-Za-z0-9\-_]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(
        r"https://hooks\.slack\.com/services/T[A-Za-z0-9_]+/B[A-Za-z0-9_]+/[A-Za-z0-9_]+"
    ),
    re.compile(
        r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9\-_]+"
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
)

_CREDENTIAL_URI_RE = re.compile(
    r"\b([a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:)([^/\s@]+)(@[^\s/]+)"
)
_QUERY_TOKEN_RE = re.compile(r"(?i)([?&]token=)[^&\s\"']+")
_BEARER_TOKEN_RE = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-+/=]{8,}")

_PLACEHOLDER_PASSWORDS = frozenset({"redacted", "password", "pass", "secret", "[redacted]"})


def _is_placeholder_secret(val: str) -> bool:
    """Return True for non-secret template placeholders like <PASS>, $PASS, *** or 'password'."""
    cleaned = val.strip()
    if not cleaned:
        return True
    if cleaned[0] in ("<", "$", "*"):
        return True
    return cleaned.lower() in _PLACEHOLDER_PASSWORDS


def assert_no_secrets_or_injection(content: str, subject: str = "") -> None:
    """Reject memories containing high-signal secrets, credential URIs, or Helios envelope markers."""
    for text in (content, subject):
        if not text:
            continue
        for pat in _INJECTION_PATTERNS:
            if pat.search(text):
                raise ValueError(
                    "Security gate rejected memory: content contains reserved Helios directive or envelope markers."
                )
        for pat in _SECRET_PATTERNS:
            if pat.search(text):
                raise ValueError(
                    "Security gate rejected memory: detected potential secret or credential. "
                    "Store the environment variable name (e.g., HELIOS_API_KEY) instead of the raw secret value."
                )
        for match in _CREDENTIAL_URI_RE.finditer(text):
            if not _is_placeholder_secret(match.group(2)):
                raise ValueError(
                    "Security gate rejected memory: detected potential secret or credential. "
                    "Store the environment variable name (e.g., HELIOS_API_KEY) instead of the raw secret value."
                )


def redact_secrets(text: str) -> str:
    """Scrub query tokens, Bearer tokens, credentialed URIs, and API keys from logs/errors."""
    if not text:
        return text
    scrubbed = _QUERY_TOKEN_RE.sub(r"\1[REDACTED]", text)
    scrubbed = _BEARER_TOKEN_RE.sub(r"\1[REDACTED]", scrubbed)
    scrubbed = _CREDENTIAL_URI_RE.sub(
        lambda m: m.group(0) if _is_placeholder_secret(m.group(2)) else f"{m.group(1)}[REDACTED]{m.group(3)}",
        scrubbed,
    )
    for pat in _SECRET_PATTERNS:
        scrubbed = pat.sub("[REDACTED]", scrubbed)
    return scrubbed


__all__ = [
    "assert_no_secrets_or_injection",
    "redact_secrets",
]
