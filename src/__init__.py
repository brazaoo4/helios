"""Helios: Token-budgeted, drift-aware MCP memory engine."""

import re
from pathlib import Path


def _resolve_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8")
            match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
            if match:
                return match.group(1)
        except Exception:  # pragma: no cover
            pass
    try:  # pragma: no cover
        from importlib.metadata import version

        return version("helios-mcp")
    except Exception:  # pragma: no cover
        return "1.0.0"


__version__ = _resolve_version()

