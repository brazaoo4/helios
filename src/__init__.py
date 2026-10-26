"""Helios: Token-budgeted, drift-aware MCP memory engine."""

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("helios-mcp")
except (PackageNotFoundError, ImportError):
    __version__ = "1.0.0"
