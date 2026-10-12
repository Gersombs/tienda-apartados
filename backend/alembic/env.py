#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Desc   :

import asyncio
import importlib
import pkgutil
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool


def clear_backend_import_cache():
    roots = ("core.database", "models")
    prefixes = tuple(f"{root}." for root in roots)
    for module_name in list(sys.modules):
        if module_name in roots or module_name.startswith(prefixes):
            sys.modules.pop(module_name, None)
    importlib.invalidate_caches()


clear_backend_import_cache()
from core.database import Base
from core.database_url import (
    create_configured_async_engine,
    database_engine_configuration,
)
import models

# Automatically import all ORM models under Models
for _, module_name, _ in pkgutil.iter_modules(models.__path__):
    importlib.import_module(f"{models.__name__}.{module_name}")

config = context.config

from core.config import settings


def _configured_database_url() -> str:
    """Return Alembic's explicit URL or the validated application setting.

    ConfigParser preserves quote characters, so ``sqlalchemy.url = ""`` is a
    non-empty string even though it does not name a database. Treat blank,
    whitespace-only and quoted-empty values as absent.
    """

    configured = (config.get_main_option("sqlalchemy.url") or "").strip()
    if configured in {"", '""', "''"}:
        configured = (
            settings.migration_database_url.strip()
            or settings.database_url.strip()
        )
    if not configured:
        raise RuntimeError("DATABASE_URL no puede estar vacío.")
    return configured


configured_pool_mode = config.attributes.get("database_pool_mode")
if configured_pool_mode is None:
    configured_pool_mode = (
        settings.migration_database_pool_mode
        if settings.migration_database_url.strip()
        else settings.database_pool_mode
    )
database_target = database_engine_configuration(
    _configured_database_url(),
    pool_mode=configured_pool_mode,
)
inherited_connect_args = config.attributes.get("database_connect_args", {})
config.set_main_option("sqlalchemy.url", database_target.url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def alembic_include_object(object, name, type_, reflected, compare_to):
    # type_ can be 'table', 'index', 'column', 'constraint'
    # ignore particular table_name
    return True


async def run_migrations_online():
    connectable = create_configured_async_engine(
        database_target,
        poolclass=pool.NullPool,
        connect_args=inherited_connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda sync_conn: context.configure(
                connection=sync_conn,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
                include_object=alembic_include_object,
            )
        )
        async with connection.begin():
            await connection.run_sync(lambda sync_conn: context.run_migrations())
    await connectable.dispose()


def run_migrations():
    try:
        # If there is no event loop currently, use asyncio.run directly
        loop = asyncio.get_running_loop()
        loop.create_task(run_migrations_online())
    except RuntimeError:
        asyncio.run(run_migrations_online())


run_migrations()
