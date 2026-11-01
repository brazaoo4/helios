"""Tests for Helios CLI entrypoint."""

import sys
from unittest.mock import patch

from src.cli import main


def test_cli_stdio_mode():
    """Verify default CLI runs init_db and mcp.run in stdio mode."""
    with patch.object(sys, "argv", ["helios"]):
        with patch("src.cli.init_db") as mock_init, patch("src.cli.mcp.run") as mock_mcp:
            main()
            mock_init.assert_called_once()
            mock_mcp.assert_called_once_with(transport="stdio")


def test_cli_serve_mode():
    """Verify helios serve runs uvicorn."""
    with patch.object(sys, "argv", ["helios", "serve"]):
        with patch("uvicorn.run") as mock_uvicorn:
            main()
            mock_uvicorn.assert_called_once()


def test_cli_http_flag_mode():
    """Verify helios --http runs uvicorn."""
    with patch.object(sys, "argv", ["helios", "--http"]):
        with patch("uvicorn.run") as mock_uvicorn:
            main()
            mock_uvicorn.assert_called_once()
