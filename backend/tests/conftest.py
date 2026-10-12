from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest


TEST_DIR = Path(tempfile.mkdtemp(prefix="nebula-tests-"))
TEST_DB = TEST_DIR / "test.db"
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{TEST_DB.as_posix()}",
        "AUTH_SECRET": "test-only-secret-that-is-longer-than-thirty-two-characters",
        "AUTO_MIGRATE": "true",
        "LOAD_SEED_DATA": "true",
        "ALLOWED_ORIGINS": "http://testserver",
        "PUBLIC_SITE_URL": "http://testserver",
        "DISABLE_FILE_LOGS": "1",
    }
)

from fastapi.testclient import TestClient

from core.auth import hash_password, private_token_hash
from core.config import settings
from main import app
from routers.auth import login_limiter
from routers.shop import reservation_limiter


ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct horse battery staple"


def db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(TEST_DB, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        with db_connection() as db:
            db.execute(
                """
                INSERT INTO admin_accounts
                    (auth_user_id, email, normalized_email, password_hash, name, role, is_active)
                VALUES (?, ?, ?, ?, ?, 'owner', 1)
                """,
                (str(uuid.uuid4()), ADMIN_EMAIL, ADMIN_EMAIL, hash_password(ADMIN_PASSWORD), "Admin de pruebas"),
            )
            db.commit()
        yield test_client


@pytest.fixture(autouse=True)
def clean_auth_state(client: TestClient):
    client.cookies.clear()
    login_limiter.reset_for_tests()
    reservation_limiter.reset_for_tests()
    yield
    client.cookies.clear()


def login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200, response.text
    csrf = client.cookies.get(settings.csrf_cookie_name)
    assert csrf
    return csrf


def reservation_payload(client: TestClient, *, variant_id: int | None = None, email: str | None = None) -> dict:
    if variant_id is None:
        products = client.get("/api/v1/shop/products").json()["items"]
        detail = client.get(f"/api/v1/shop/products/{products[0]['slug']}").json()["product"]
        variant_id = next(item["id"] for item in detail["variants"] if item["available_units"] > 0)
    delivery = client.get("/api/v1/shop/delivery-options").json()["delivery_points"]
    point = next(point for point in delivery if any(day["slots"] for day in point["days"]))
    day = next(day for day in point["days"] if day["slots"])
    slot = day["slots"][0]
    return {
        "full_name": "Clienta de Prueba",
        "whatsapp": "5512345678",
        "email": email or f"clienta+{uuid.uuid4().hex}@example.com",
        "delivery_point_id": point["id"],
        "delivery_date": day["date"],
        "slot_start": slot["start_time"],
        "notes": "",
        "privacy_accepted": True,
        "fingerprint": uuid.uuid4().hex,
        "items": [{"variant_id": variant_id, "quantity": 1}],
    }


def create_reservation(client: TestClient, **overrides):
    payload = reservation_payload(client, variant_id=overrides.pop("variant_id", None), email=overrides.pop("email", None))
    payload.update(overrides)
    response = client.post("/api/v1/shop/reservations", json=payload)
    assert response.status_code == 200, response.text
    return response.json(), payload
