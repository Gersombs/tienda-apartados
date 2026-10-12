"""AWS Lambda entry point for the API and a prebuilt single-page frontend."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from mangum import Mangum

from main import app


DIST_DIR = (Path(__file__).resolve().parent.parent / "frontend" / "dist").resolve()
API_HANDLER = Mangum(app, lifespan="off")
PRIVATE_PREFIXES = ("/admin", "/confirmacion", "/apartado", "/auth/")
STATIC_MIME_TYPES = {
    ".avif": "image/avif",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
}


def _request_path(event: dict[str, Any]) -> str:
    request_context = event.get("requestContext") or {}
    http_context = request_context.get("http") or {}
    return unquote(event.get("rawPath") or http_context.get("path") or event.get("path") or "/")


def _method(event: dict[str, Any]) -> str:
    request_context = event.get("requestContext") or {}
    http_context = request_context.get("http") or {}
    return str(http_context.get("method") or event.get("httpMethod") or "GET").upper()


def _response(status: int, body: bytes = b"", *, content_type: str = "text/plain; charset=utf-8", headers=None):
    response_headers = {
        "Content-Type": content_type,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        **(headers or {}),
    }
    return {
        "statusCode": status,
        "headers": response_headers,
        "body": base64.b64encode(body).decode("ascii") if body else "",
        "isBase64Encoded": bool(body),
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


def _serve_frontend(path: str, method: str) -> dict[str, Any]:
    if method not in {"GET", "HEAD"}:
        return _response(405, headers={"Allow": "GET, HEAD"})
    if not DIST_DIR.is_dir():
        return _response(503, b"Frontend build unavailable")

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
        return _response(404, b"Not found")
    else:
        asset = DIST_DIR / "index.html"
        cache_control = "no-cache"

    content_type = _content_type(asset)
    if content_type.startswith("text/") or content_type in {"application/javascript", "application/json", "image/svg+xml"}:
        content_type += "; charset=utf-8"
    extra_headers = {"Cache-Control": cache_control}
    if content_type.startswith("text/html"):
        extra_headers.update(
            {
                "Content-Security-Policy": "frame-ancestors 'none'",
                "X-Frame-Options": "DENY",
            }
        )
    if path.startswith(PRIVATE_PREFIXES):
        extra_headers.update(
            {
                "Cache-Control": "no-store",
                "X-Robots-Tag": "noindex, nofollow, noarchive",
            }
        )
    if path.startswith("/confirmacion"):
        extra_headers["Referrer-Policy"] = "no-referrer"
    body = b"" if method == "HEAD" else asset.read_bytes()
    return _response(200, body, content_type=content_type, headers=extra_headers)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    path = _request_path(event)
    if path == "/health" or path.startswith("/api/"):
        return API_HANDLER(event, context)
    return _serve_frontend(path, _method(event))
