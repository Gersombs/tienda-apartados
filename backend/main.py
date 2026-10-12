"""Nébula Beauty MX API composition root.

Only the explicitly imported routers below are reachable. Generated entity,
storage, AI, user and environment-settings routers are intentionally excluded.
"""

from __future__ import annotations

import logging
import os
import re
import traceback
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from core.config import settings
from core.reservation_limits import MAX_RESERVATION_BODY_BYTES
from dependencies.auth import get_current_admin_account, require_csrf
from frontend import serve_frontend
from routers.auth import router as auth_router
from routers.crm import router as crm_router
from routers.shop import router as shop_router
from services.database import close_database, initialize_database
from services.migrations import upgrade_database
from services.mock_data import initialize_mock_data


SENSITIVE_LOG_PATTERN = re.compile(
    r"(?i)(authorization|cookie|password|secret|token|clabe|resend_api_key)(\s*[:=]\s*)([^\s,;]+)"
)

PUBLIC_ENDPOINTS = frozenset(
    {
        ("GET", "/health"),
        ("POST", "/api/v1/auth/login"),
        ("GET", "/api/v1/shop/bootstrap"),
        ("GET", "/api/v1/shop/products"),
        ("GET", "/api/v1/shop/products/{slug}"),
        ("GET", "/api/v1/shop/delivery-options"),
        ("POST", "/api/v1/shop/availability"),
        ("POST", "/api/v1/shop/reservations"),
        ("POST", "/api/v1/shop/confirmation"),
        ("GET", "/api/v1/shop/content"),
        ("GET", "/api/v1/shop/images/{image_id}"),
    }
)
PROTECTED_AUTH_ENDPOINTS = frozenset(
    {
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/logout"),
    }
)


def _public_path_pattern(template: str) -> re.Pattern[str]:
    segments = template.split("/")
    expression = "/".join(
        r"[^/]+" if segment.startswith("{") and segment.endswith("}") else re.escape(segment)
        for segment in segments
    )
    return re.compile(f"^{expression}$")


PUBLIC_ROUTE_PATTERNS = tuple(
    (method, _public_path_pattern(path)) for method, path in PUBLIC_ENDPOINTS
)


class ReservationBodyLimitMiddleware:
    """Apply a streaming body limit only to public reservation creation."""

    def __init__(self, app: ASGIApp, max_body_size: int) -> None:
        self.app = app
        self.limited_app = RequestBodyLimitMiddleware(app, max_body_size=max_body_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/api/v1/shop/reservations"
        ):
            await self.limited_app(scope, receive, send)
            return
        await self.app(scope, receive, send)


def is_public_request(method: str, path: str) -> bool:
    return any(method == expected and pattern.fullmatch(path) for expected, pattern in PUBLIC_ROUTE_PATTERNS)


def is_crm_path(path: str) -> bool:
    return path == "/api/v1/crm" or path.startswith("/api/v1/crm/")


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = SENSITIVE_LOG_PATTERN.sub(r"\1\2[REDACTED]", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if not settings.is_production and os.environ.get("DISABLE_FILE_LOGS", "").lower() not in {"1", "true"}:
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"app_{datetime.now():%Y%m%d}.log")
        handlers.insert(0, logging.FileHandler(log_file, mode="a", encoding="utf-8"))
    redactor = RedactingFilter()
    for handler in handlers:
        handler.addFilter(redactor)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.auto_migrate:
        await upgrade_database()
    await initialize_database()
    if settings.load_seed_data:
        await initialize_mock_data()
    yield
    await close_database()


setup_logging()
app = FastAPI(
    title=settings.app_name,
    description="API de catálogo y solicitudes de apartado de Nébula Beauty MX",
    version=settings.version,
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
    expose_headers=["Content-Disposition", "X-Exported-Rows"],
)
app.add_middleware(
    ReservationBodyLimitMiddleware,
    max_body_size=MAX_RESERVATION_BODY_BYTES,
)


@app.middleware("http")
async def anonymous_admin_gate(request: Request, call_next):
    """Reject anonymous CRM traffic before body parsing or endpoint dispatch."""
    if is_crm_path(request.url.path) and not request.cookies.get(settings.session_cookie_name):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "La sesión administrativa no es válida."},
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow, noarchive"},
        )
    return await call_next(request)


@app.middleware("http")
async def api_surface_gate(request: Request, call_next):
    """Deny undeclared API routes; new endpoints are unreachable by default."""
    method_path = (request.method, request.url.path)
    if request.method != "OPTIONS" and request.url.path.startswith("/api/v1/") and not (
        is_public_request(*method_path)
        or method_path in PROTECTED_AUTH_ENDPOINTS
        or is_crm_path(request.url.path)
    ):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Not Found"},
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow, noarchive"},
        )
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    private_token_response = request.method == "POST" and (
        request.url.path == "/api/v1/shop/reservations"
        or request.url.path.endswith("/rotate-confirmation-token")
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = (
        "no-referrer"
        if request.url.path in {"/api/v1/shop/confirmation", "/confirmacion"} or private_token_response
        else "strict-origin-when-cross-origin"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith(("/api/v1/crm", "/api/v1/auth", "/api/v1/shop/confirmation")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    if private_token_response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


app.include_router(shop_router)
app.include_router(auth_router)
app.include_router(
    crm_router,
    dependencies=[Depends(get_current_admin_account), Depends(require_csrf)],
)


@app.exception_handler(Exception)
async def general_exception_handler(_request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    logging.getLogger(__name__).error("Unhandled %s", type(exc).__name__, exc_info=True)
    if settings.environment == "dev" and settings.debug:
        detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    else:
        detail = "Internal Server Error"
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": detail})


@app.get("/health", include_in_schema=False)
def health_check():
    return {"status": "ok"}


# Registrada al final: todo lo que no es API ni /health es la SPA o un archivo del build.
@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def spa(path: str):
    return serve_frontend(f"/{path}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.environment == "dev")
