"""Typed application configuration with production safety checks."""

from __future__ import annotations

from functools import cached_property
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from core.database_url import DatabasePoolMode, normalize_database_url
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent
DEV_AUTH_SECRET = "dev-only-nebula-secret-change-before-production"


class Settings(BaseSettings):
    app_name: str = "Nébula Beauty MX API"
    version: str = "1.0.0-rc1"
    environment: Literal["dev", "test", "production"] = "dev"
    # DEBUG is a common host/build variable (and may contain values such as
    # "release"). Use an application-specific name so unrelated environment
    # variables cannot prevent settings from loading.
    debug: bool = Field(default=False, validation_alias="APP_DEBUG")
    log_level: str = "INFO"

    host: str = "127.0.0.1"
    port: int = 8000
    public_site_url: str = "http://localhost:3000"
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # SQLite is convenient locally; PostgreSQL is required in production for
    # real row-level locking and the concurrency guarantees it provides.
    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'nebula_dev.db').as_posix()}"
    database_pool_mode: DatabasePoolMode = "auto"
    # Prefer a direct PostgreSQL endpoint for schema changes. When omitted,
    # Alembic uses DATABASE_URL with the same pooler safeguards as runtime.
    migration_database_url: str = ""
    migration_database_pool_mode: DatabasePoolMode = "auto"
    auto_migrate: bool = True
    load_seed_data: bool = True

    auth_secret: str = DEV_AUTH_SECRET
    session_cookie_name: str = "nebula_admin_session"
    csrf_cookie_name: str = "nebula_csrf"
    session_lifetime_minutes: int = Field(default=480, ge=15, le=10080)
    login_max_attempts: int = Field(default=5, ge=2, le=20)
    login_window_seconds: int = Field(default=900, ge=60, le=86400)

    resend_api_key: str = ""
    admin_email: str = ""
    email_from_address: str = ""
    email_from_name: str = "Nébula Beauty MX"
    # Clave de servidor de Google (Places API New) para sugerir direcciones en el CRM; vacía = sin sugerencias.
    google_maps_api_key: str = ""
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR.parent / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @cached_property
    def cors_origins(self) -> tuple[str, ...]:
        return tuple(origin.strip() for origin in self.allowed_origins.split(",") if origin.strip())

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.is_production

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        origins = self.cors_origins
        if not origins:
            raise ValueError("ALLOWED_ORIGINS must contain at least one explicit origin")
        if "*" in origins:
            raise ValueError("Wildcard CORS origins are not allowed when credentials are enabled")
        for origin in origins:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"Invalid CORS origin: {origin}")

        if self.is_production:
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if self.auth_secret == DEV_AUTH_SECRET or len(self.auth_secret) < 32:
                raise ValueError("AUTH_SECRET must be unique and at least 32 characters in production")
            if self.auto_migrate:
                raise ValueError("AUTO_MIGRATE must be false in production; run Alembic as a release step")
            if self.load_seed_data:
                raise ValueError("LOAD_SEED_DATA must be false in production")
            if len(origins) != 1:
                raise ValueError("ALLOWED_ORIGINS must contain exactly one origin in production")
            allowed_origin = _production_origin(origins[0], "ALLOWED_ORIGINS")
            public_origin = _production_origin(self.public_site_url, "PUBLIC_SITE_URL")
            if public_origin != allowed_origin:
                raise ValueError(
                    "PUBLIC_SITE_URL and ALLOWED_ORIGINS must be the same origin in production"
                )
            try:
                normalized_database = normalize_database_url(self.database_url)
            except ValueError as exc:
                raise ValueError("A valid PostgreSQL DATABASE_URL is required in production") from exc
            if not normalized_database.url.startswith("postgresql+asyncpg://"):
                raise ValueError("A PostgreSQL DATABASE_URL is required in production")
            if self.migration_database_url:
                try:
                    migration_database = normalize_database_url(self.migration_database_url)
                except ValueError as exc:
                    raise ValueError(
                        "MIGRATION_DATABASE_URL must be a valid PostgreSQL URL"
                    ) from exc
                if not migration_database.url.startswith("postgresql+asyncpg://"):
                    raise ValueError("MIGRATION_DATABASE_URL must use PostgreSQL")
        return self


def _production_origin(value: str, field_name: str) -> str:
    """Validate and return one canonical public HTTPS origin."""

    raw = value
    if raw != raw.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    parsed = urlparse(raw)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{field_name} must be a canonical public HTTPS origin")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError(f"{field_name} must include a public hostname")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} contains an invalid port") from exc
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError(f"{field_name} cannot use localhost in production")
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        raise ValueError(f"{field_name} must use a DNS hostname, not an IP literal")
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    canonical_port = f":{port}" if port not in {None, 443} else ""
    canonical = f"https://{rendered_host}{canonical_port}"
    if raw != canonical:
        raise ValueError(f"{field_name} must not contain a path or trailing slash")
    return canonical


settings = Settings()
