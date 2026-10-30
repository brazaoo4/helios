"""Tests for HTTP export endpoints (/export/markdown and /export/bundle)."""

import tarfile
from io import BytesIO

from starlette.testclient import TestClient

from src.server import app, save_memory


def test_export_http_endpoints():
    save_memory(scope="infrastructure", category="rule", content="Pin all docker container versions")

    with TestClient(app) as client:
        # Test /export/markdown
        res_md = client.get("/export/markdown")
        assert res_md.status_code == 200
        exports = res_md.json()["exports"]
        assert any(e["scope"] == "infrastructure" for e in exports)

        # Test /export/bundle download
        res_bundle = client.get("/export/bundle")
        assert res_bundle.status_code == 200
        assert res_bundle.headers["content-type"] == "application/gzip"
        assert len(res_bundle.content) > 0

        # Verify downloaded stream is a valid tar.gz containing memory.db
        with tarfile.open(fileobj=BytesIO(res_bundle.content), mode="r:gz") as tar:
            names = tar.getnames()
            assert "memory.db" in names
            assert any(n.startswith("exports") for n in names)


def test_export_endpoints_edge_cases(monkeypatch, tmp_path):
    import src.routes.exports as exp_mod

    # 1. Non-existent export directory returns empty list
    non_existent = tmp_path / "does_not_exist"
    monkeypatch.setattr(exp_mod, "get_export_dir", lambda: non_existent)
    assert exp_mod._scan_markdown_exports() == []

    # 2. Bundle generation error returns 500
    def _broken_bundle():
        raise RuntimeError("Disk full")

    monkeypatch.setattr(exp_mod, "create_portable_archive", _broken_bundle)
    with TestClient(app) as client:
        res = client.get("/export/bundle")
        assert res.status_code == 500
        assert "Disk full" in res.json()["message"]

