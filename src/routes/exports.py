"""HTTP endpoints for downloading portable archives and listing Markdown exports."""

from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from src.exporter import create_portable_archive, get_export_dir


async def export_bundle_download(request: Request) -> Response:
    """
    HTTP GET endpoint to download the latest helios_portable_bundle.tar.gz.
    Generates a fresh snapshot on demand in a worker thread.
    """
    try:
        archive_path = await anyio.to_thread.run_sync(create_portable_archive)
        return FileResponse(
            path=archive_path,
            filename="helios_portable_bundle.tar.gz",
            media_type="application/gzip",
        )
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"Failed to generate bundle: {exc}"},
            status_code=500,
        )


def _scan_markdown_exports() -> list[dict[str, Any]]:
    export_dir = get_export_dir()
    if not export_dir.exists():
        return []

    files: list[dict[str, Any]] = []
    for file_path in sorted(export_dir.glob("*.md")):
        files.append(
            {
                "scope": file_path.stem,
                "filename": file_path.name,
                "size_bytes": file_path.stat().st_size,
            }
        )
    return files


async def list_markdown_exports(request: Request) -> JSONResponse:
    """
    HTTP GET endpoint listing all generated markdown files and sizes.
    """
    files = await anyio.to_thread.run_sync(_scan_markdown_exports)
    return JSONResponse({"exports": files}, status_code=200)


__all__ = [
    "_scan_markdown_exports",
    "export_bundle_download",
    "list_markdown_exports",
]
