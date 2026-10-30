"""Tests for FastMCP admin and operational tools (export_bundle)."""

from src.server import export_bundle, save_memory


def test_mcp_export_bundle_tool():
    save_memory(scope="infrastructure", category="fact", content="Docker subnet is 172.20.0.0/16")
    res = export_bundle()
    assert "Snapshot created:" in res
    assert "helios_portable_bundle.tar.gz" in res
