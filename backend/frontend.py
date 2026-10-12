"""Serve the prebuilt single-page frontend from the same origin as the API."""

from __future__ import annotations

import mimetypes
from pathlib import Path, PurePosixPath

from fastapi import Response
from fastapi.responses import FileResponse


DIST_DIR = (Path(__file__).resolve().parent.parent / "frontend" / "dist").resolve()
PRIVATE_PREFIXES = ("/admin", "/confirmacion", "/apartado", "/auth/")
STATIC_MIME_TYPES = {
    ".avif": "image/avif",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
}


def _safe_asset(path: str) -> Path | None:
    relative = PurePosixPath(path.lstrip("/"))
    if any(part in {"", ".", ".."} for part in relative.parts):
        return None
    candidate = (DIST_DIR / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(DIST_DIR)
    except ValueError:
        return None
    return candidate


def _content_type(asset: Path) -> str:
    return STATIC_MIME_TYPES.get(asset.suffix.lower()) or mimetypes.guess_type(asset.name)[0] or "application/octet-stream"


def serve_frontend(path: str) -> Response:
    if path.startswith("/api/"):
        return Response(status_code=404, content="Not found")
    if not DIST_DIR.is_dir():
        return Response(status_code=503, content="Frontend build unavailable")

    requested = _safe_asset(path)
    if requested is not None and requested.is_file():
        asset = requested
        if path.startswith("/assets/"):
            cache_control = "public, max-age=31536000, immutable"
        elif path.startswith("/images/"):
            cache_control = "public, max-age=604800, stale-while-revalidate=86400"
        else:
            cache_control = "public, max-age=3600"
    elif PurePosixPath(path).suffix:
        return Response(status_code=404, content="Not found")
    else:
        asset = DIST_DIR / "index.html"
        cache_control = "no-cache"

    content_type = _content_type(asset)
    if content_type.startswith("text/") or content_type in {"application/javascript", "application/json", "image/svg+xml"}:
        content_type += "; charset=utf-8"
    headers = {"Cache-Control": cache_control}
    if content_type.startswith("text/html"):
        headers.update(
            {
                "Content-Security-Policy": "frame-ancestors 'none'",
                "X-Frame-Options": "DENY",
            }
        )
    if path.startswith(PRIVATE_PREFIXES):
        headers.update(
            {
                "Cache-Control": "no-store",
                "X-Robots-Tag": "noindex, nofollow, noarchive",
            }
        )
    return FileResponse(asset, media_type=content_type, headers=headers)
