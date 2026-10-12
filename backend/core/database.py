"""Asynchronous database lifecycle; Alembic is the only schema writer."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from core.config import settings
from core.database_url import (
    DatabaseEngineConfiguration,
    create_configured_async_engine,
    database_engine_configuration,
)
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class DatabaseManager:
    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.async_session_maker: async_sessionmaker[AsyncSession] | None = None
        self._init_lock = asyncio.Lock()
        self._initialization_task: asyncio.Task[None] | None = None

    @staticmethod
    def _engine_options(target: DatabaseEngineConfiguration) -> dict[str, Any]:
        options: dict[str, Any] = {"echo": settings.debug}
        if target.url.startswith("sqlite") or target.transaction_pooler:
            return options

        # Un solo contenedor por tienda: pocas conexiones bastan y caben en planes gratuitos.
        options.update(
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_recycle=300,
            pool_timeout=30,
        )
        return options

    async def _initialize(self) -> None:
        if not settings.database_url:
            raise ValueError("DATABASE_URL is required")

        target = database_engine_configuration(
            settings.database_url,
            pool_mode=settings.database_pool_mode,
        )
        engine_options = self._engine_options(target)
        engine = create_configured_async_engine(target, **engine_options)
        try:
            if target.url.startswith("sqlite"):

                @event.listens_for(engine.sync_engine, "connect")
                def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.close()

            session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            # Publish both references only after initialization has succeeded.
            self.engine = engine
            self.async_session_maker = session_maker
            logger.info("Database connection initialized")
        except Exception:
            await engine.dispose()
            raise

    async def init_db(self) -> None:
        """Initialize once and share the same in-flight task between callers."""
        if self.async_session_maker is not None:
            return
        async with self._init_lock:
            if self.async_session_maker is not None:
                return
            if self._initialization_task is None or self._initialization_task.done():
                self._initialization_task = asyncio.create_task(self._initialize())
            task = self._initialization_task
        await task

    async def ensure_initialized(self) -> None:
        if self.async_session_maker is None:
            logger.warning("Database not initialized; initializing lazily")
            await self.init_db()

    async def close_db(self) -> None:
        engine = self.engine
        self.engine = None
        self.async_session_maker = None
        self._initialization_task = None
        if engine is not None:
            await engine.dispose()
            logger.info("Database connection closed")


db_manager = DatabaseManager()


async def get_db():
    """Yield one transaction-capable session per request."""
    started = time.monotonic()
    await db_manager.ensure_initialized()
    session_maker = db_manager.async_session_maker
    if session_maker is None:
        raise RuntimeError("Database initialization failed")

    async with session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            logger.debug("Database session lifetime %.4fs", time.monotonic() - started)
