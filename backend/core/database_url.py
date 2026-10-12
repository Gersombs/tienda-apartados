"""Database URL normalization shared by the application and Alembic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool


POSTGRES_DRIVERS = frozenset({"postgres", "postgresql", "postgresql+asyncpg"})
SQLITE_DRIVERS = frozenset({"sqlite", "sqlite+aiosqlite"})
ASYNCPG_SSL_MODES = frozenset(
    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)
DatabasePoolMode = Literal["auto", "direct", "transaction"]


@dataclass(frozen=True, slots=True)
class NormalizedDatabaseURL:
    """An async SQLAlchemy URL plus driver-only connection arguments."""

    url: str
    connect_args: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DatabaseEngineConfiguration:
    """Normalized connection details and transaction-pooler safeguards."""

    url: str
    connect_args: dict[str, Any]
    transaction_pooler: bool
    force_null_pool: bool


def _unique_prepared_statement_name() -> str:
    """Avoid prepared-statement name collisions across PgBouncer clients."""

    return f"__asyncpg_{uuid4().hex}__"


def normalize_database_url(raw_url: str) -> NormalizedDatabaseURL:
    """Normalize supported URLs without connecting or exposing credentials.

    SQLAlchemy's asyncpg dialect does not accept provider query arguments such
    as ``sslmode`` or ``channel_binding``.  asyncpg does accept the standard
    libpq SSL modes through its ``ssl`` connection argument, so that value is
    moved out of the URL instead of being discarded.
    """

    try:
        parsed = make_url(raw_url.strip())
    except Exception as exc:
        raise ValueError("DATABASE_URL is not a valid SQLAlchemy URL") from exc

    driver = parsed.drivername or ""
    connect_args: dict[str, Any] = {}
    if driver in POSTGRES_DRIVERS:
        parsed = parsed.set(drivername="postgresql+asyncpg")
        sslmode = parsed.query.get("sslmode")
        if isinstance(sslmode, tuple):
            sslmode = sslmode[-1] if sslmode else None
        if sslmode is not None:
            normalized_mode = str(sslmode).strip().lower()
            if normalized_mode not in ASYNCPG_SSL_MODES:
                raise ValueError("DATABASE_URL contains an unsupported PostgreSQL sslmode")
            connect_args["ssl"] = normalized_mode
        parsed = parsed.difference_update_query(["sslmode", "channel_binding"])
    elif driver in SQLITE_DRIVERS:
        parsed = parsed.set(drivername="sqlite+aiosqlite")
    else:
        raise ValueError("Only PostgreSQL/asyncpg and SQLite/aiosqlite are supported")

    return NormalizedDatabaseURL(
        url=parsed.render_as_string(hide_password=False),
        connect_args=connect_args,
    )


def _looks_like_transaction_pooler(database_url: str) -> bool:
    """Detect common provider pooler endpoints without inspecting credentials."""

    parsed = make_url(database_url)
    if parsed.drivername != "postgresql+asyncpg":
        return False
    hostname = (parsed.host or "").lower()
    return "pooler" in hostname or "pgbouncer" in hostname or parsed.port == 6543


def database_engine_configuration(
    raw_url: str,
    *,
    pool_mode: DatabasePoolMode = "auto",
) -> DatabaseEngineConfiguration:
    """Build the shared runtime/Alembic connection policy.

    Transaction poolers cannot safely retain client-side prepared statements
    between transactions. SQLAlchemy's asyncpg emulation and asyncpg itself
    have separate caches, so both are disabled for that mode. Direct
    connections retain their defaults.
    """

    if pool_mode not in {"auto", "direct", "transaction"}:
        raise ValueError("Database pool mode must be auto, direct, or transaction")

    normalized = normalize_database_url(raw_url)
    is_postgres = normalized.url.startswith("postgresql+asyncpg://")
    transaction_pooler = is_postgres and (
        pool_mode == "transaction"
        or (pool_mode == "auto" and _looks_like_transaction_pooler(normalized.url))
    )
    connect_args = dict(normalized.connect_args)
    if transaction_pooler:
        connect_args.update(
            prepared_statement_cache_size=0,
            statement_cache_size=0,
            prepared_statement_name_func=_unique_prepared_statement_name,
        )

    return DatabaseEngineConfiguration(
        url=normalized.url,
        connect_args=connect_args,
        transaction_pooler=transaction_pooler,
        force_null_pool=transaction_pooler,
    )


def create_configured_async_engine(
    target: DatabaseEngineConfiguration,
    **engine_options: Any,
) -> AsyncEngine:
    """Create an engine while enforcing the selected connection policy."""

    options = dict(engine_options)
    caller_connect_args = dict(options.pop("connect_args", {}) or {})
    connect_args = {**caller_connect_args, **target.connect_args}
    if connect_args:
        options["connect_args"] = connect_args
    if target.force_null_pool:
        options["poolclass"] = NullPool
        for incompatible in (
            "pool_size",
            "max_overflow",
            "pool_recycle",
            "pool_timeout",
            "pool_pre_ping",
        ):
            options.pop(incompatible, None)
    return create_async_engine(target.url, **options)
