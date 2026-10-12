"""Bloqueos reales de PostgreSQL al apartar.

Las demás pruebas usan SQLite, donde un candado del proceso oculta `FOR UPDATE`.
Sólo corre con TEST_DATABASE_URL apuntando a una base desechable (por ejemplo,
una rama de Neon creada para esto): migra el esquema y deja datos de prueba.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from core.database_url import create_configured_async_engine, database_engine_configuration
from models.delivery_points import Delivery_points
from models.delivery_slots import Delivery_slots
from models.product_variants import Product_variants
from models.products import Products
from services.reservation_engine import ReservationError, create_reservation, today_mx


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL.startswith("postgres"), reason="TEST_DATABASE_URL de PostgreSQL no configurada"
)
BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def session_maker():
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL, "MIGRATION_DATABASE_URL": "", "AUTO_MIGRATE": "false", "LOAD_SEED_DATA": "false"}
    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=180, check=False,
    )
    assert migrated.returncode == 0, migrated.stderr
    engine = create_configured_async_engine(database_engine_configuration(TEST_DATABASE_URL), poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    asyncio.run(engine.dispose())


async def _setup(maker, *, stock: int, capacity: int) -> tuple[int, int, str]:
    day = today_mx() + timedelta(days=1)
    async with maker() as db:
        point = Delivery_points(name="Punto concurrencia", sort_order=0, is_active=True)
        product = Products(name="Producto concurrencia", slug=f"pg-{uuid.uuid4().hex}", price=99)
        db.add_all([point, product])
        await db.flush()
        variant = Product_variants(
            product_id=product.id, option_name="", option_value="", stock=stock, reserved_stock=0, price_delta=0
        )
        db.add_all([
            variant,
            Delivery_slots(
                delivery_point_id=point.id, weekday=day.weekday(), start_time="10:00",
                end_time="11:00", capacity=capacity, is_active=True,
            ),
        ])
        await db.commit()
        return point.id, variant.id, day.isoformat()


async def _race(maker, point_id: int, variant_id: int, day: str) -> list[str]:
    async def reserve(index: int) -> str:
        async with maker() as db:
            try:
                await create_reservation(db, {
                    "full_name": "Clienta Concurrencia",
                    "whatsapp": "5512345678",
                    "email": f"pg-{index}-{uuid.uuid4().hex}@example.com",
                    "delivery_point_id": point_id,
                    "delivery_date": day,
                    "slot_start": "10:00",
                    "notes": "",
                    "privacy_accepted": True,
                    "fingerprint": uuid.uuid4().hex,
                    "items": [{"variant_id": variant_id, "quantity": 1}],
                })
                return "ok"
            except ReservationError as exc:
                await db.rollback()
                return exc.message

    return list(await asyncio.gather(*(reserve(i) for i in range(4))))


async def _reserved(maker, variant_id: int) -> int:
    async with maker() as db:
        variant = (await db.execute(select(Product_variants).where(Product_variants.id == variant_id))).scalar_one()
        return variant.reserved_stock


def test_postgres_only_one_request_gets_the_last_unit(session_maker):
    async def scenario():
        ids = await _setup(session_maker, stock=1, capacity=0)
        results = await _race(session_maker, *ids)
        return results, await _reserved(session_maker, ids[1])

    results, reserved = asyncio.run(scenario())
    assert results.count("ok") == 1, results
    assert reserved == 1


def test_postgres_slot_capacity_holds_under_concurrency(session_maker):
    async def scenario():
        ids = await _setup(session_maker, stock=10, capacity=1)
        results = await _race(session_maker, *ids)
        return results, await _reserved(session_maker, ids[1])

    results, reserved = asyncio.run(scenario())
    assert results.count("ok") == 1, results
    assert reserved == 1
