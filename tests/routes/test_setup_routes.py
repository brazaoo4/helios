"""Tests for HTTP onboarding and setup/uninstall endpoints (/setup, /setup.ps1, /setup.sh, /uninstall, etc.)."""

from starlette.testclient import TestClient

from src.onboarding import generate_uninstall_powershell
from src.server import app


def test_http_setup_endpoint_open_mode():
    with TestClient(app) as client:
        res = client.get("/setup", headers={"Host": "helios.local:8000"})
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/markdown")
        content = res.text
        assert "Helios AI-Driven Client Onboarding" in content
        assert "http://helios.local:8000" in content
        assert "mcp_config.json" in content
        assert "name: remember" in content
        assert "manage_git_webhooks" in content


def test_http_setup_endpoint_with_auth_and_no_leak(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "super-secret-production-token-999")

    with TestClient(app) as client:
        # 1. Unauthenticated request to /setup must succeed (exempt from AuthGate)
        res = client.get(
            "/setup",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "helios.internal.net",
            },
        )
        assert res.status_code == 200
        content = res.text

        # Base URL must be correctly resolved from headers
        assert "https://helios.internal.net" in content

        # CRITICAL ZERO-LEAK CHECK: The actual secret key must NEVER be printed!
        assert "super-secret-production-token-999" not in content

        # It must instruct the agent to ask the user
        assert "<YOUR_HELIOS_API_KEY>" in content
        assert "Authentication Required" in content

        # 2. When query param ?token= supplied by user, it is safely rendered in snippets
        res_with_token = client.get(
            "/setup?token=user-client-token-abc",
            headers={"Host": "helios.example.com", "X-Forwarded-Proto": "https"},
        )
        assert res_with_token.status_code == 200
        assert "user-client-token-abc" in res_with_token.text
        assert "https://helios.example.com/mcp?token=user-client-token-abc" in res_with_token.text


def test_http_setup_powershell_and_bash_endpoints(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "super-secret-auth-key-123")

    with TestClient(app) as client:
        # 1. PowerShell setup script endpoint (exempt from AuthGate)
        res_ps1 = client.get(
            "/setup.ps1",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "helios.mesh.net"},
        )
        assert res_ps1.status_code == 200
        ps1_text = res_ps1.text
        assert "Helios Automated Client Setup for Windows PowerShell" in ps1_text
        assert "https://helios.mesh.net/mcp" in ps1_text
        assert "mcp_config.json" in ps1_text
        assert "<!-- HELIOS:START -->" in ps1_text
        assert "super-secret-auth-key-123" not in ps1_text

        # 2. PowerShell script with user token query param
        res_ps1_token = client.get(
            "/setup.ps1?token=client-token-xyz",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "helios.mesh.net"},
        )
        assert res_ps1_token.status_code == 200
        assert "https://helios.mesh.net/mcp?token=client-token-xyz" in res_ps1_token.text

        # 3. Bash setup script endpoint (exempt from AuthGate)
        res_sh = client.get(
            "/setup.sh",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "helios.mesh.net"},
        )
        assert res_sh.status_code == 200
        sh_text = res_sh.text
        assert "#!/usr/bin/env bash" in sh_text
        assert "https://helios.mesh.net/mcp" in sh_text
        assert "mcp_config.json" in sh_text
        assert "<!-- HELIOS:START -->" in sh_text
        assert "super-secret-auth-key-123" not in sh_text


def test_http_uninstall_endpoints(monkeypatch):
    monkeypatch.setenv("HELIOS_API_KEY", "super-secret-auth-key-123")

    with TestClient(app) as client:
        # 1. /uninstall (markdown guide)
        res_ui = client.get(
            "/uninstall",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "helios.mesh.net"},
        )
        assert res_ui.status_code == 200
        assert "Helios Client Uninstallation Guide" in res_ui.text
        assert "curl -fsSL https://helios.mesh.net/uninstall.sh | bash" in res_ui.text

        # 2. /uninstall.sh (bash script)
        res_sh = client.get("/uninstall.sh")
        assert res_sh.status_code == 200
        assert "#!/usr/bin/env bash" in res_sh.text
        assert "Uninstalling Helios client configuration" in res_sh.text
        assert "helios-write-through-guard" in res_sh.text
        assert "super-secret-auth-key-123" not in res_sh.text

        # 3. /uninstall.ps1 (powershell script)
        res_ps1 = client.get("/uninstall.ps1")
        assert res_ps1.status_code == 200
        assert "Helios Automated Client Uninstaller for Windows PowerShell" in res_ps1.text
        assert "helios-write-through-guard" in res_ps1.text

        # Verify generate_uninstall_powershell helper output directly
        ps_direct = generate_uninstall_powershell(client="cursor")
        assert "client: cursor" in ps_direct
        assert "Remove-HeliosDirective" in ps_direct
