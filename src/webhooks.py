"""
Helios Git Webhook Manager Module.

Provides provider-agnostic repository discovery, noise filtering, and drift
webhook lifecycle management across Forgejo, Gitea, GitHub, and GitLab.
"""

import ipaddress
import os
import socket
import urllib.parse
from typing import Any

import httpx

from src.config import (
    get_git_api_url,
    get_git_owner,
    get_git_provider,
    get_git_token,
    get_webhook_secret,
    get_webhook_url,
    resolve_setting_with_source,
    validate_http_url,
)
from src.db import get_connection, list_aliases, resolve_scope


def normalize_api_url(provider: str, raw_url: str | None = None) -> str:
    """Normalize the API base URL based on provider."""
    p = (provider or "").strip().lower()
    raw = (raw_url or "").strip()

    if not raw:
        if p == "github":
            return "https://api.github.com"
        if p == "gitlab":
            return "https://gitlab.com/api/v4"
        raise ValueError(f"API URL is required for provider '{p}'.")

    url = raw.rstrip("/")
    if p in ("forgejo", "gitea"):
        if not url.endswith("/api/v1"):
            url = f"{url}/api/v1"
    elif p == "gitlab":
        if not url.endswith("/api/v4"):
            url = f"{url}/api/v4"

    return url


def get_headers(provider: str, token: str) -> dict[str, str]:
    """Return appropriate HTTP headers for API authentication."""
    p = provider.strip().lower()
    if p == "github":
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    elif p == "gitlab":
        return {
            "PRIVATE-TOKEN": token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    else:  # forgejo, gitea
        return {
            "Authorization": f"token {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }


def _get_authenticated_user(client: httpx.Client, provider: str, api_url: str) -> str:
    """Fetch the authenticated username for ownership filtering."""
    provider.strip().lower()
    endpoint = f"{api_url}/user"
    res = client.get(endpoint)
    if res.status_code == 200:
        data = res.json()
        if isinstance(data, dict):
            return data.get("username") or data.get("login") or ""
    return ""


def get_known_helios_scopes() -> set[str]:
    """Return all known active scopes and aliases in the Helios database."""
    scopes: set[str] = set()
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT scope FROM memories WHERE status IN ('active', 'stale') AND valid_to IS NULL"
            ).fetchall()
            for r in rows:
                scopes.add(r["scope"].lower())
            aliases = list_aliases()
            for alias, canonical in aliases.items():
                scopes.add(alias.lower())
                scopes.add(canonical.lower())
    except Exception:
        pass
    return scopes


def match_helios_scope(repo_name: str, full_name: str, known_scopes: set[str]) -> str | None:
    """Check if repository matches an active scope or alias in Helios."""
    candidates = [
        resolve_scope(repo_name).lower(),
        resolve_scope(full_name).lower(),
        repo_name.lower(),
        full_name.lower(),
    ]
    for c in candidates:
        if c in known_scopes:
            return c
    return None


def fetch_candidate_repositories(
    client: httpx.Client,
    provider: str,
    api_url: str,
    target_owner: str,
    include_forks: bool = False,
) -> list[dict[str, Any]]:
    """
    List repositories owned by target_owner, applying strict ownership,
    fork, and archived filtering.
    """
    p = provider.strip().lower()
    repos: list[dict[str, Any]] = []
    page = 1
    per_page = 100 if p in ("github", "gitlab") else 50
    owner_lower = target_owner.lower()

    while True:
        if p == "github":
            url = f"{api_url}/user/repos"
            params: dict[str, Any] = {"affiliation": "owner", "per_page": per_page, "page": page}
            res = client.get(url, params=params)
            if res.status_code != 200 and target_owner:
                enc_owner = urllib.parse.quote(target_owner, safe="")
                url = f"{api_url}/orgs/{enc_owner}/repos"
                res = client.get(url, params={"per_page": per_page, "page": page})
        elif p == "gitlab":
            url = f"{api_url}/projects"
            params = {"owned": "true", "per_page": per_page, "page": page}
            res = client.get(url, params=params)
            if res.status_code != 200 and target_owner:
                enc_owner = urllib.parse.quote(target_owner, safe="")
                url = f"{api_url}/groups/{enc_owner}/projects"
                res = client.get(url, params={"per_page": per_page, "page": page})
        else:  # forgejo, gitea
            url = f"{api_url}/user/repos"
            params = {"limit": per_page, "page": page}
            res = client.get(url, params=params)
            if res.status_code != 200 and target_owner:
                enc_owner = urllib.parse.quote(target_owner, safe="")
                url = f"{api_url}/orgs/{enc_owner}/repos"
                res = client.get(url, params={"limit": per_page, "page": page})

        if res.status_code != 200:
            break

        batch = res.json()
        if not batch or not isinstance(batch, list):
            break

        for item in batch:
            if p == "gitlab":
                repo_owner = (item.get("namespace") or {}).get("path") or ""
                repo_name = item.get("name") or item.get("path") or ""
                full_name = item.get("path_with_namespace") or f"{repo_owner}/{repo_name}"
                is_fork = bool(item.get("forked_from_project") or item.get("fork"))
                is_archived = bool(item.get("archived"))
                repo_id = item.get("id")
            else:
                repo_owner = (item.get("owner") or {}).get("login") or ""
                repo_name = item.get("name") or ""
                full_name = item.get("full_name") or f"{repo_owner}/{repo_name}"
                is_fork = bool(item.get("fork"))
                is_archived = bool(item.get("archived"))
                repo_id = item.get("id")

            # Strict Ownership Filtering: must match target_owner
            if owner_lower and repo_owner.lower() != owner_lower:
                continue

            # Noise Filtering: exclude archived repos
            if is_archived:
                continue

            # Noise Filtering: exclude forks unless explicitly included
            if is_fork and not include_forks:
                continue

            repos.append({
                "owner": repo_owner,
                "name": repo_name,
                "full_name": full_name,
                "is_fork": is_fork,
                "is_archived": is_archived,
                "repo_id": repo_id,
            })

        if len(batch) < per_page:
            break
        page += 1

    return repos


def _assert_safe_outbound_url(url: str) -> None:
    """Validate destination URL and ensure resolved IP addresses do not target forbidden ranges."""
    clean_url = validate_http_url(url, allow_loopback=False)
    parsed = urllib.parse.urlsplit(clean_url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a valid hostname.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            v4 = ip.ipv4_mapped if (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped) else ip
            if ip.is_link_local or v4.is_link_local or ip_str.startswith("169.254.") or str(v4) == "100.100.100.200":
                raise ValueError(f"Destination IP '{ip_str}' is forbidden.")
            in_zero_net = isinstance(v4, ipaddress.IPv4Address) and v4 in ipaddress.ip_network("0.0.0.0/8")
            if ip.is_loopback or v4.is_loopback or ip.is_unspecified or in_zero_net:
                raise ValueError(f"Destination IP '{ip_str}' is forbidden.")
    except (socket.gaierror, OSError):
        pass


def _validate_repo_ident(owner: str, name: str) -> None:
    if not owner or owner in (".", "..") or "/" in owner or "\\" in owner:
        raise ValueError(f"Invalid repository owner: {owner!r}")
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"Invalid repository name: {name!r}")


def _verify_token_destination_allowed(
    target_api_url: str,
    explicit_token: str | None = None,
    sending_env_webhook_secret: bool = False,
) -> None:
    """Refuse to send environment-sourced secrets to an untrusted runtime DB URL override."""
    try:
        _, token_source = resolve_setting_with_source("HELIOS_GIT_TOKEN")
        _, url_source = resolve_setting_with_source("HELIOS_GIT_API_URL")
        _, prov_source = resolve_setting_with_source("HELIOS_GIT_PROVIDER")
    except KeyError:
        return

    has_env_token = explicit_token is None and token_source == "env"
    has_env_secret = sending_env_webhook_secret and bool(get_webhook_secret())

    if (has_env_token or has_env_secret) and (url_source == "db" or prov_source == "db"):
        env_prov = (os.getenv("HELIOS_GIT_PROVIDER") or "").strip().lower()
        env_raw_url = (os.getenv("HELIOS_GIT_API_URL") or "").strip()
        try:
            expected_env_url = normalize_api_url(env_prov, env_raw_url)
        except ValueError as exc:
            raise ValueError(
                f"Security violation: environment secret configured without matching environment Git API destination ('{target_api_url}')."
            ) from exc
        p_env = urllib.parse.urlsplit(expected_env_url)
        p_target = urllib.parse.urlsplit(target_api_url)
        if (p_env.scheme.lower(), p_env.netloc.lower()) != (p_target.scheme.lower(), p_target.netloc.lower()):
            raise ValueError(
                f"Security violation: HELIOS_GIT_TOKEN is configured in environment for '{p_env.netloc}' but destination is runtime DB override '{p_target.netloc}'."
            )


def get_repo_hooks(
    client: httpx.Client,
    provider: str,
    api_url: str,
    owner: str,
    repo_name: str,
    full_name: str,
) -> list[dict[str, Any]]:
    """Fetch all webhooks for a given repository."""
    p = provider.strip().lower()
    if p == "gitlab":
        encoded = urllib.parse.quote(full_name, safe="")
        endpoint = f"{api_url}/projects/{encoded}/hooks"
    else:
        _validate_repo_ident(owner, repo_name)
        enc_owner = urllib.parse.quote(owner, safe="")
        enc_name = urllib.parse.quote(repo_name, safe="")
        endpoint = f"{api_url}/repos/{enc_owner}/{enc_name}/hooks"

    res = client.get(endpoint)
    if res.status_code == 200:
        data = res.json()
        return data if isinstance(data, list) else []
    return []


def find_helios_hook(hooks: list[dict[str, Any]], webhook_url: str) -> dict[str, Any] | None:
    """Find hook matching HELIOS_WEBHOOK_URL."""
    clean_target = webhook_url.strip().rstrip("/")
    for h in hooks:
        cfg = h.get("config") or {}
        h_url = (cfg.get("url") or h.get("url") or "").strip().rstrip("/")
        if h_url == clean_target:
            return h
    return None


def list_repo_webhooks(
    include_forks: bool = False,
    provider: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
    owner: str | None = None,
    webhook_url: str | None = None,
) -> list[dict[str, Any]]:
    """
    List all owned repositories with their current Helios webhook status
    and matched Helios memory scope.
    """
    prov = (provider or get_git_provider()).strip().lower()
    base_url = normalize_api_url(prov, api_url or get_git_api_url())
    _assert_safe_outbound_url(base_url)
    auth_token = token or get_git_token()
    if not auth_token:
        raise ValueError("Git API token is missing or not configured.")

    _verify_token_destination_allowed(base_url, explicit_token=token)

    target_url = (webhook_url or get_webhook_url()).strip()
    headers = get_headers(prov, auth_token)
    known_scopes = get_known_helios_scopes()

    with httpx.Client(headers=headers, timeout=15.0) as client:
        target_owner = (owner or get_git_owner() or _get_authenticated_user(client, prov, base_url)).strip()
        candidates = fetch_candidate_repositories(client, prov, base_url, target_owner, include_forks)

        results = []
        for c in candidates:
            hooks = get_repo_hooks(client, prov, base_url, c["owner"], c["name"], c["full_name"])
            matched_hook = find_helios_hook(hooks, target_url) if target_url else None
            matched_scope = match_helios_scope(c["name"], c["full_name"], known_scopes)

            results.append({
                "repo": c["full_name"],
                "name": c["name"],
                "owner": c["owner"],
                "enabled": matched_hook is not None,
                "hook_id": matched_hook["id"] if matched_hook else None,
                "is_fork": c["is_fork"],
                "is_archived": c["is_archived"],
                "matched_scope": matched_scope,
            })

        return results


def enable_repo_webhooks(
    repos: list[str],
    provider: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
) -> dict[str, Any]:
    """
    Idempotently attach the Helios push webhook to specified repositories.
    """
    if not repos:
        raise ValueError("No repositories specified to enable.")

    prov = (provider or get_git_provider()).strip().lower()
    base_url = normalize_api_url(prov, api_url or get_git_api_url())
    _assert_safe_outbound_url(base_url)
    auth_token = token or get_git_token()
    if not auth_token:
        raise ValueError("Git API token is missing or not configured.")

    target_url = (webhook_url or get_webhook_url()).strip()
    if not target_url:
        raise ValueError("HELIOS_WEBHOOK_URL is required to enable webhooks.")

    secret = (webhook_secret or get_webhook_secret() or "").strip()
    _verify_token_destination_allowed(
        base_url,
        explicit_token=token,
        sending_env_webhook_secret=(webhook_secret is None and bool(secret)),
    )
    headers = get_headers(prov, auth_token)

    enabled: list[str] = []
    already_enabled: list[str] = []
    failed: list[dict[str, str]] = []

    with httpx.Client(headers=headers, timeout=15.0) as client:
        default_owner = None
        for repo_identifier in repos:
            clean_repo = repo_identifier.strip()
            if "/" in clean_repo:
                owner, name = clean_repo.split("/", 1)
            else:
                if default_owner is None:
                    default_owner = (get_git_owner() or _get_authenticated_user(client, prov, base_url)).strip()
                owner, name = default_owner, clean_repo

            try:
                _validate_repo_ident(owner, name)
                hooks = get_repo_hooks(client, prov, base_url, owner, name, clean_repo)
                existing = find_helios_hook(hooks, target_url)
                if existing:
                    already_enabled.append(clean_repo)
                    continue

                # Create hook
                if prov == "gitlab":
                    encoded = urllib.parse.quote(clean_repo, safe="")
                    endpoint = f"{base_url}/projects/{encoded}/hooks"
                    payload = {
                        "url": target_url,
                        "push_events": True,
                        "token": secret,
                        "enable_ssl_verification": True,
                    }
                elif prov == "github":
                    enc_owner = urllib.parse.quote(owner, safe="")
                    enc_name = urllib.parse.quote(name, safe="")
                    endpoint = f"{base_url}/repos/{enc_owner}/{enc_name}/hooks"
                    payload = {
                        "name": "web",
                        "active": True,
                        "events": ["push"],
                        "config": {
                            "url": target_url,
                            "content_type": "json",
                            "secret": secret,
                            "insecure_ssl": "0",
                        },
                    }
                else:  # forgejo, gitea
                    enc_owner = urllib.parse.quote(owner, safe="")
                    enc_name = urllib.parse.quote(name, safe="")
                    endpoint = f"{base_url}/repos/{enc_owner}/{enc_name}/hooks"
                    payload = {
                        "type": "gitea",
                        "config": {
                            "url": target_url,
                            "content_type": "json",
                            "secret": secret,
                        },
                        "events": ["push"],
                        "active": True,
                    }

                res = client.post(endpoint, json=payload)
                if res.status_code in (200, 201):
                    enabled.append(clean_repo)
                else:
                    failed.append({"repo": clean_repo, "error": f"HTTP {res.status_code}: {res.text[:200]}"})
            except Exception as exc:
                failed.append({"repo": clean_repo, "error": str(exc)})

    return {
        "enabled": enabled,
        "already_enabled": already_enabled,
        "failed": failed,
    }


def disable_repo_webhooks(
    repos: list[str],
    provider: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
    webhook_url: str | None = None,
) -> dict[str, Any]:
    """
    Remove the Helios push webhook from specified repositories.
    """
    if not repos:
        raise ValueError("No repositories specified to disable.")

    prov = (provider or get_git_provider()).strip().lower()
    base_url = normalize_api_url(prov, api_url or get_git_api_url())
    _assert_safe_outbound_url(base_url)
    auth_token = token or get_git_token()
    if not auth_token:
        raise ValueError("Git API token is missing or not configured.")

    _verify_token_destination_allowed(base_url, explicit_token=token)

    target_url = (webhook_url or get_webhook_url()).strip()
    if not target_url:
        raise ValueError("HELIOS_WEBHOOK_URL is required to identify webhooks.")

    headers = get_headers(prov, auth_token)

    disabled: list[str] = []
    not_found: list[str] = []
    failed: list[dict[str, str]] = []

    with httpx.Client(headers=headers, timeout=15.0) as client:
        default_owner = None
        for repo_identifier in repos:
            clean_repo = repo_identifier.strip()
            if "/" in clean_repo:
                owner, name = clean_repo.split("/", 1)
            else:
                if default_owner is None:
                    default_owner = (get_git_owner() or _get_authenticated_user(client, prov, base_url)).strip()
                owner, name = default_owner, clean_repo

            try:
                _validate_repo_ident(owner, name)
                hooks = get_repo_hooks(client, prov, base_url, owner, name, clean_repo)
                existing = find_helios_hook(hooks, target_url)
                if not existing:
                    not_found.append(clean_repo)
                    continue

                hook_id = existing["id"]
                if prov == "gitlab":
                    encoded = urllib.parse.quote(clean_repo, safe="")
                    endpoint = f"{base_url}/projects/{encoded}/hooks/{hook_id}"
                else:
                    enc_owner = urllib.parse.quote(owner, safe="")
                    enc_name = urllib.parse.quote(name, safe="")
                    endpoint = f"{base_url}/repos/{enc_owner}/{enc_name}/hooks/{hook_id}"

                res = client.delete(endpoint)
                if res.status_code in (200, 204):
                    disabled.append(clean_repo)
                else:
                    failed.append({"repo": clean_repo, "error": f"HTTP {res.status_code}: {res.text[:200]}"})
            except Exception as exc:
                failed.append({"repo": clean_repo, "error": str(exc)})

    return {
        "disabled": disabled,
        "not_found": not_found,
        "failed": failed,
    }
