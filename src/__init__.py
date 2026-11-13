"""Helios: Token-budgeted, drift-aware MCP memory engine."""

import tomllib
from pathlib import Path


def _resolve_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            pkg_version = data.get("project", {}).get("version")
            if isinstance(pkg_version, str) and pkg_version.strip():
                return pkg_version.strip()
        except Exception:  # pragma: no cover
            pass
    try:  # pragma: no cover
        from importlib.metadata import version

        return version("helios-mcp")
    except Exception:  # pragma: no cover
        return "1.0.0"


__version__ = _resolve_version()

