"""Serve the prebuilt single-page frontend from the same origin as the API."""

from __future__ import annotations

import html
import json
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
DEFAULT_SHOP_NAME = "Nébula Beauty MX"

# Paletas que la tienda puede elegir (color_accent) y su color de barra del navegador.
# Las variables de cada una viven en frontend/src/index.css bajo [data-paleta="..."].
PALETTES = {
    "cereza": "#B8123F",
    "nude": "#A35533",
    "malva": "#894D77",
    "esmeralda": "#1E674E",
    "noche": "#171717",
    "coral": "#BF3A22",
}
DEFAULT_THEME_COLOR = '<meta name="theme-color" content="#B8123F" />'


def _json_text(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


# Archivos del build donde el nombre por defecto se sustituye por el de la tienda.
BRANDED_FILES = {
    "index.html": [(DEFAULT_SHOP_NAME, lambda name: html.escape(name, quote=True))],
    "site.webmanifest": [
        (f'"{DEFAULT_SHOP_NAME}"', lambda name: f'"{_json_text(name)}"'),
        ('"Nébula Beauty"', lambda name: f'"{_json_text(name)}"'),
    ],
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


def serve_frontend(path: str, shop_name: str | None = None, palette: str | None = None) -> Response:
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
    palette = palette if palette in PALETTES else None
    if (shop_name or palette) and asset.name in BRANDED_FILES:
        # El build trae el nombre por defecto; cada tienda muestra el suyo (título, vista previa al compartir, manifest).
        branded = asset.read_text(encoding="utf-8")
        for default, escape in BRANDED_FILES[asset.name] if shop_name else []:
            branded = branded.replace(default, escape(shop_name))
        if palette and asset.name == "index.html":
            # En el HTML para que los colores salgan bien desde el primer pintado, también en el enlace privado.
            branded = branded.replace("<html ", f'<html data-paleta="{palette}" ', 1).replace(
                DEFAULT_THEME_COLOR, f'<meta name="theme-color" content="{PALETTES[palette]}" />'
            )
        return Response(branded, media_type=content_type, headers=headers)
    return FileResponse(asset, media_type=content_type, headers=headers)
