#!/usr/bin/env python3
"""
Helios Provider-Agnostic Webhook Provisioning CLI.

Idempotently provisions Helios Git push drift detection webhooks across
repositories in Forgejo, Gitea, or GitHub organizations and user accounts.
"""

import argparse
import os
import sys
from typing import Any
import httpx


def normalize_api_url(provider: str, raw_url: str | None) -> str:
    """Normalize the API base URL based on provider."""
    if not raw_url or not raw_url.strip():
        if provider == "github":
            return "https://api.github.com"
        raise ValueError(f"--api-url is required for provider '{provider}'.")

    url = raw_url.strip().rstrip("/")
    if provider in ("forgejo", "gitea"):
        if not url.endswith("/api/v1"):
            url = f"{url}/api/v1"
    return url


def get_headers(provider: str, token: str) -> dict[str, str]:
    """Return appropriate HTTP headers for API authentication."""
    if provider == "github":
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    else:  # forgejo, gitea
        return {
            "Authorization": f"token {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }


def list_repositories(
    client: httpx.Client,
    provider: str,
    api_url: str,
    owner: str | None = None,
) -> list[dict[str, Any]]:
    """List all repositories for user or organization."""
    repos: list[dict[str, Any]] = []
    page = 1
    per_page = 100 if provider == "github" else 50

    while True:
        if owner:
            if provider == "github":
                # Try org repos first; fallback to user repos
                url = f"{api_url}/orgs/{owner}/repos"
                res = client.get(url, params={"per_page": per_page, "page": page})
                if res.status_code == 404:
                    url = f"{api_url}/users/{owner}/repos"
                    res = client.get(url, params={"per_page": per_page, "page": page})
            else:
                # Forgejo / Gitea
                url = f"{api_url}/orgs/{owner}/repos"
                res = client.get(url, params={"limit": per_page, "page": page})
                if res.status_code == 404:
                    url = f"{api_url}/users/{owner}/repos"
                    res = client.get(url, params={"limit": per_page, "page": page})
        else:
            if provider == "github":
                url = f"{api_url}/user/repos"
                res = client.get(url, params={"per_page": per_page, "page": page})
            else:
                url = f"{api_url}/user/repos"
                res = client.get(url, params={"limit": per_page, "page": page})

        if res.status_code != 200:
            raise RuntimeError(f"Failed to fetch repositories ({res.status_code}): {res.text}")

        batch = res.json()
        if not batch or not isinstance(batch, list):
            break

        for item in batch:
            repo_owner = item.get("owner", {}).get("login") or (owner or "")
            repo_name = item.get("name", "")
            full_name = item.get("full_name") or f"{repo_owner}/{repo_name}"
            repos.append({
                "owner": repo_owner,
                "name": repo_name,
                "full_name": full_name,
            })

        if len(batch) < per_page:
            break
        page += 1

    return repos


def list_webhooks(
    client: httpx.Client,
    api_url: str,
    owner: str,
    repo: str,
) -> list[dict[str, Any]]:
    """List existing webhooks for a repository."""
    url = f"{api_url}/repos/{owner}/{repo}/hooks"
    res = client.get(url)
    if res.status_code == 404:
        return []
    if res.status_code != 200:
        raise RuntimeError(f"Failed to fetch hooks for {owner}/{repo} ({res.status_code}): {res.text}")
    data = res.json()
    return data if isinstance(data, list) else []


def webhook_already_exists(hooks: list[dict[str, Any]], target_webhook_url: str) -> bool:
    """Check if target_webhook_url is already registered."""
    clean_target = target_webhook_url.strip().rstrip("/")
    for hook in hooks:
        hook_config = hook.get("config") or {}
        hook_url = (hook_config.get("url") or hook.get("url") or "").strip().rstrip("/")
        if hook_url == clean_target:
            return True
    return False


def create_webhook(
    client: httpx.Client,
    provider: str,
    api_url: str,
    owner: str,
    repo: str,
    webhook_url: str,
    secret: str = "",
) -> bool:
    """Create push webhook on repository."""
    endpoint = f"{api_url}/repos/{owner}/{repo}/hooks"
    if provider == "github":
        payload = {
            "name": "web",
            "active": True,
            "events": ["push"],
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "secret": secret,
                "insecure_ssl": "0",
            },
        }
    else:  # forgejo, gitea
        payload = {
            "type": "gitea",
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "secret": secret,
            },
            "events": ["push"],
            "active": True,
        }

    res = client.post(endpoint, json=payload)
    if res.status_code in (200, 201):
        return True
    raise RuntimeError(f"Failed to create webhook on {owner}/{repo} ({res.status_code}): {res.text}")


def sync_webhooks(
    provider: str,
    api_url: str,
    token: str,
    webhook_url: str,
    webhook_secret: str = "",
    owner: str | None = None,
) -> dict[str, int]:
    """Idempotently sync webhooks across repositories."""
    norm_url = normalize_api_url(provider, api_url)
    headers = get_headers(provider, token)

    stats = {
        "total_repos": 0,
        "registered": 0,
        "skipped": 0,
        "errors": 0,
    }

    with httpx.Client(headers=headers, timeout=15.0) as client:
        print(f"[*] Discovering repositories on {provider} ({norm_url})...")
        repos = list_repositories(client, provider, norm_url, owner)
        stats["total_repos"] = len(repos)
        print(f"[*] Found {len(repos)} repositories.")

        for repo_info in repos:
            repo_owner = repo_info["owner"]
            repo_name = repo_info["name"]
            full_name = repo_info["full_name"]

            try:
                hooks = list_webhooks(client, norm_url, repo_owner, repo_name)
                if webhook_already_exists(hooks, webhook_url):
                    print(f"  [SKIPPED] {full_name} (webhook already registered)")
                    stats["skipped"] += 1
                else:
                    create_webhook(
                        client,
                        provider,
                        norm_url,
                        repo_owner,
                        repo_name,
                        webhook_url,
                        webhook_secret,
                    )
                    print(f"  [REGISTERED] {full_name} -> {webhook_url}")
                    stats["registered"] += 1
            except Exception as exc:
                print(f"  [ERROR] {full_name}: {exc}", file=sys.stderr)
                stats["errors"] += 1

    print(
        f"\n[+] Sync complete: {stats['registered']} registered, "
        f"{stats['skipped']} skipped, {stats['errors']} errors "
        f"across {stats['total_repos']} repositories."
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotently provision Helios Git push drift detection webhooks across repos."
    )
    parser.add_argument(
        "--provider",
        choices=["forgejo", "gitea", "github"],
        default=os.getenv("GIT_PROVIDER", "forgejo"),
        help="Git provider (forgejo, gitea, or github). Default: forgejo",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("GIT_API_URL"),
        help="Base URL for Git API (e.g. https://git.example.com or https://api.github.com)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GIT_API_TOKEN"),
        help="API access token (or set GIT_API_TOKEN)",
    )
    parser.add_argument(
        "--owner",
        default=os.getenv("GIT_OWNER"),
        help="Organization or username (optional, defaults to authenticated user repos)",
    )
    parser.add_argument(
        "--webhook-url",
        default=os.getenv("HELIOS_WEBHOOK_URL"),
        help="Helios webhook endpoint (e.g. http://helios:8000/webhook/git)",
    )
    parser.add_argument(
        "--webhook-secret",
        default=os.getenv("HELIOS_WEBHOOK_SECRET", ""),
        help="Shared HMAC webhook secret (or set HELIOS_WEBHOOK_SECRET)",
    )

    args = parser.parse_args()

    api_url = args.api_url
    if not api_url:
        if args.provider == "github":
            api_url = "https://api.github.com"
        else:
            parser.error("--api-url is required for provider (or set GIT_API_URL).")

    if not args.token:
        parser.error("--token is required (or set GIT_API_TOKEN).")

    if not args.webhook_url:
        parser.error("--webhook-url is required (or set HELIOS_WEBHOOK_URL).")

    try:
        stats = sync_webhooks(
            provider=args.provider,
            api_url=api_url,
            token=args.token,
            webhook_url=args.webhook_url,
            webhook_secret=args.webhook_secret or "",
            owner=args.owner,
        )
        if stats["errors"] > 0 and stats["registered"] == 0 and stats["skipped"] == 0:
            sys.exit(1)
    except Exception as exc:
        print(f"Error during webhook sync: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
