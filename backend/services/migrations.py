"""Alembic orchestration used only for explicitly enabled local startup."""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config

from core.config import BACKEND_DIR, settings
from core.database_url import database_engine_configuration


def _upgrade_sync() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    configured_url = settings.migration_database_url.strip() or settings.database_url
    pool_mode = (
        settings.migration_database_pool_mode
        if settings.migration_database_url.strip()
        else settings.database_pool_mode
    )
    target = database_engine_configuration(configured_url, pool_mode=pool_mode)
    config.set_main_option("sqlalchemy.url", target.url.replace("%", "%%"))
    config.attributes["database_connect_args"] = target.connect_args
    config.attributes["database_pool_mode"] = pool_mode
    command.upgrade(config, "head")


async def upgrade_database() -> None:
    await asyncio.to_thread(_upgrade_sync)
