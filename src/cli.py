"""CLI entrypoint for Helios MCP server."""

import sys

from src.db import init_db
from src.tools.base import mcp


def main() -> None:
    """Run Helios in stdio mode (default) or HTTP mode."""
    if len(sys.argv) > 1 and sys.argv[1] in ("serve", "--http"):
        import uvicorn

        from src.server import app

        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        init_db()
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
