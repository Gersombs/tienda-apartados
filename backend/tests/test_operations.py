from __future__ import annotations

import csv
import io
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import frontend as frontend_module
import routers.crm as crm_router
from core.auth import private_token_hash
from frontend import _content_type
from services import mailer
from services.mailer import confirmation_link

from conftest import ADMIN_PASSWORD, TEST_DB, create_reservation, db_connection, login


BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_static_webp_mime_is_platform_independent():
    assert _content_type(Path("product.webp")) == "image/webp"


def test_spa_html_denies_framing_without_applying_a_broad_asset_csp(
    client, tmp_path, monkeypatch
):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Nébula</title>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(frontend_module, "DIST_DIR", dist.resolve())

    document = client.get("/")
    deep_link = client.get("/producto/labial-mate")
    confirmation = client.get("/confirmacion")
    asset = client.get("/assets/app.js")
    missing_asset = client.get("/assets/missing.js")
    traversal = client.get("/assets/..%2F..%2Fmain.py")
    unknown_api = client.get("/api/unknown")

    assert document.status_code == 200
    assert document.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    assert document.headers["X-Frame-Options"] == "DENY"
    assert deep_link.status_code == 200 and "Nébula" in deep_link.text
    assert confirmation.headers["Cache-Control"] == "no-store"
    assert confirmation.headers["Referrer-Policy"] == "no-referrer"
    assert asset.status_code == 200
    assert asset.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert "Content-Security-Policy" not in asset.headers
    assert "X-Frame-Options" not in asset.headers
    assert missing_asset.status_code == 404
    assert traversal.status_code == 404
    assert unknown_api.status_code == 404
    assert client.get("/health").json() == {"status": "ok"}


def _product_id() -> int:
    with db_connection() as db:
        return int(db.execute("SELECT id FROM products ORDER BY id LIMIT 1").fetchone()[0])


def test_variant_creation_records_only_positive_stock_and_rolls_back(client, monkeypatch):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    product_id = _product_id()

    zero = client.post(
        "/api/v1/crm/variants",
        json={
            "product_id": product_id,
            "option_name": "Prueba",
            "option_value": "Cero",
            "sku": f"ZERO-{uuid.uuid4().hex}",
            "stock": 0,
            "price_delta": 0,
            "is_active": True,
        },
        headers=headers,
    )
    assert zero.status_code == 200, zero.text
    with db_connection() as db:
        zero_movements = db.execute(
            "SELECT COUNT(*) FROM inventory_movements WHERE variant_id=?", (zero.json()["id"],)
        ).fetchone()[0]
    assert zero_movements == 0

    positive = client.post(
        "/api/v1/crm/variants",
        json={
            "product_id": product_id,
            "option_name": "Prueba",
            "option_value": "Positiva",
            "sku": f"POS-{uuid.uuid4().hex}",
            "stock": 4,
            "price_delta": 0,
            "is_active": True,
        },
        headers=headers,
    )
    assert positive.status_code == 200, positive.text
    with db_connection() as db:
        movement = db.execute(
            "SELECT movement_type, quantity FROM inventory_movements WHERE variant_id=?",
            (positive.json()["id"],),
        ).fetchone()
    assert tuple(movement) == ("entrada", 4)

    async def fail_movement(*_args, **_kwargs):
        raise RuntimeError("fallo de movimiento simulado")

    monkeypatch.setattr(crm_router, "log_movement", fail_movement)
    failed_sku = f"ROLLBACK-{uuid.uuid4().hex}"
    with pytest.raises(Exception, match="fallo de movimiento simulado"):
        client.post(
            "/api/v1/crm/variants",
            json={
                "product_id": product_id,
                "option_name": "Prueba",
                "option_value": "Rollback",
                "sku": failed_sku,
                "stock": 2,
                "price_delta": 0,
                "is_active": True,
            },
            headers=headers,
        )
    with db_connection() as db:
        assert db.execute("SELECT COUNT(*) FROM product_variants WHERE sku=?", (failed_sku,)).fetchone()[0] == 0


def test_zero_stock_adjustment_is_idempotent_and_has_no_movement(client):
    csrf = login(client)
    with db_connection() as db:
        variant = db.execute(
            "SELECT id, stock FROM product_variants WHERE stock > 0 ORDER BY id LIMIT 1"
        ).fetchone()
        before = db.execute(
            "SELECT COUNT(*) FROM inventory_movements WHERE variant_id=?", (variant["id"],)
        ).fetchone()[0]
    response = client.post(
        "/api/v1/crm/stock-adjust",
        json={"variant_id": variant["id"], "new_stock": variant["stock"], "note": "sin cambio"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    assert response.json()["stock"] == variant["stock"]
    with db_connection() as db:
        after = db.execute(
            "SELECT COUNT(*) FROM inventory_movements WHERE variant_id=?", (variant["id"],)
        ).fetchone()[0]
    assert after == before


def test_csv_export_sanitizes_formula_prefixes_and_keeps_numbers_numeric(client):
    created, _payload = create_reservation(client)
    with db_connection() as db:
        db.execute(
            """
            UPDATE reservations
            SET customer_name=?, customer_whatsapp=?, customer_email=?, delivery_point_name=?,
                customer_notes=?, internal_notes=?
            WHERE folio=?
            """,
            (
                "=1+1",
                " +cmd",
                "\t-2+3",
                "\ufeff@SUM(1,2)",
                "\x01=HYPERLINK(\"https://example.com\")",
                "\t@cmd",
                created["folio"],
            ),
        )
        db.commit()

    csrf = login(client)
    response = client.get(
        "/api/v1/crm/reservations-export",
        params={"search": created["folio"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "text/csv" in response.headers["Content-Type"]
    assert "charset=utf-8" in response.headers["Content-Type"].lower()
    assert response.headers["Content-Disposition"].startswith('attachment; filename="reservaciones-')

    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 2
    data = rows[1]
    assert data[2] == "'=1+1"
    assert data[3] == "' +cmd"
    assert data[4] == "'\t-2+3"
    assert data[5] == "'\ufeff@SUM(1,2)"
    assert data[10] == "'\x01=HYPERLINK(\"https://example.com\")"
    assert data[11] == "'\t@cmd"
    assert data[8].isdigit()
    assert float(data[9]) >= 0


def test_confirmation_rotation_revocation_fragment_and_terminal_bank_policy(client):
    created, _payload = create_reservation(client)
    token = created["private_token"]
    active = client.post("/api/v1/shop/confirmation", json={"token": token})
    assert active.status_code == 200
    assert active.json()["bank_details"]["clabe"]
    assert confirmation_link("https://shop.example.com", token) == f"https://shop.example.com/confirmacion#t={token}"

    with db_connection() as db:
        reservation_id = db.execute(
            "SELECT id FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()[0]
    csrf = login(client)
    rotated = client.post(
        f"/api/v1/crm/reservations/{reservation_id}/rotate-confirmation-token",
        headers={"X-CSRF-Token": csrf},
    )
    assert rotated.status_code == 200, rotated.text
    replacement = rotated.json()["private_token"]
    assert client.post("/api/v1/shop/confirmation", json={"token": token}).status_code == 404
    assert client.post("/api/v1/shop/confirmation", json={"token": replacement}).status_code == 200
    with db_connection() as db:
        row = db.execute(
            "SELECT private_token_hash, token_revoked FROM reservations WHERE id=?", (reservation_id,)
        ).fetchone()
    assert row["private_token_hash"] == private_token_hash(replacement)
    assert row["token_revoked"] == 0

    for terminal_status in ("cancelada", "vencida", "entregada", "no_show"):
        with db_connection() as db:
            db.execute("UPDATE reservations SET status=? WHERE id=?", (terminal_status, reservation_id))
            db.commit()
        terminal = client.post("/api/v1/shop/confirmation", json={"token": replacement})
        assert terminal.status_code == 200
        assert not any(terminal.json()["bank_details"].values())

    terminal_rotation = client.post(
        f"/api/v1/crm/reservations/{reservation_id}/rotate-confirmation-token",
        headers={"X-CSRF-Token": csrf},
    )
    assert terminal_rotation.status_code == 409

    revoked = client.post(
        f"/api/v1/crm/reservations/{reservation_id}/revoke-confirmation-token",
        headers={"X-CSRF-Token": csrf},
    )
    assert revoked.status_code == 200
    assert client.post("/api/v1/shop/confirmation", json={"token": replacement}).status_code == 404


def test_admin_generates_and_sends_a_usable_private_link(client, monkeypatch, caplog):
    created, _payload = create_reservation(client)
    old_token = created["private_token"]
    with db_connection() as db:
        reservation_id = db.execute(
            "SELECT id FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()[0]

    sent_html: list[str] = []

    async def successful_provider(_api_key, _sender, _to, _subject, html):
        sent_html.append(html)
        return {"ok": True, "message_id": "provider-message-test"}

    monkeypatch.setattr(mailer.app_settings, "resend_api_key", "test-provider-key")
    monkeypatch.setattr(mailer, "_send_via_resend", successful_provider)
    csrf = login(client)

    unsafe_resend = client.post(
        f"/api/v1/crm/reservations/{reservation_id}/resend",
        json={"template": mailer.TEMPLATE_RECEIVED},
        headers={"X-CSRF-Token": csrf},
    )
    assert unsafe_resend.status_code == 400

    rotated = client.post(
        f"/api/v1/crm/reservations/{reservation_id}/rotate-confirmation-token",
        headers={"X-CSRF-Token": csrf},
    )
    assert rotated.status_code == 200, rotated.text
    body = rotated.json()
    new_token = body["private_token"]
    assert body["email_sent"] is True
    assert body["recovery_required"] is False
    assert rotated.headers["Cache-Control"] == "no-store"
    assert rotated.headers["Pragma"] == "no-cache"
    assert rotated.headers["Referrer-Policy"] == "no-referrer"
    assert sent_html and f"/confirmacion#t={new_token}" in sent_html[0]
    assert client.post("/api/v1/shop/confirmation", json={"token": old_token}).status_code == 404
    assert client.post("/api/v1/shop/confirmation", json={"token": new_token}).status_code == 200

    with db_connection() as db:
        row = db.execute(
            "SELECT private_token_hash FROM reservations WHERE id=?", (reservation_id,)
        ).fetchone()
        notification_text = str(
            db.execute(
                "SELECT subject, error_message, provider_message_id FROM notifications "
                "WHERE reservation_id=?",
                (reservation_id,),
            ).fetchall()
        )
    assert row["private_token_hash"] == private_token_hash(new_token)
    assert new_token not in notification_text
    assert new_token not in caplog.text


def test_failed_private_link_email_returns_recoverable_new_link(client, monkeypatch, caplog):
    created, _payload = create_reservation(client)
    old_token = created["private_token"]
    with db_connection() as db:
        reservation_id = db.execute(
            "SELECT id FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()[0]

    async def failed_provider(_api_key, _sender, _to, _subject, _html):
        return {"ok": False, "error": "provider unavailable"}

    monkeypatch.setattr(mailer.app_settings, "resend_api_key", "test-provider-key")
    monkeypatch.setattr(mailer, "_send_via_resend", failed_provider)
    csrf = login(client)
    rotated = client.post(
        f"/api/v1/crm/reservations/{reservation_id}/rotate-confirmation-token",
        headers={"X-CSRF-Token": csrf},
    )
    assert rotated.status_code == 200, rotated.text
    body = rotated.json()
    new_token = body["private_token"]
    assert body["email_sent"] is False
    assert body["recovery_required"] is True
    assert body["email_status"][0]["status"] == "fallido"
    assert client.post("/api/v1/shop/confirmation", json={"token": old_token}).status_code == 404
    assert client.post("/api/v1/shop/confirmation", json={"token": new_token}).status_code == 200
    with db_connection() as db:
        stored_hash = db.execute(
            "SELECT private_token_hash FROM reservations WHERE id=?", (reservation_id,)
        ).fetchone()[0]
    assert stored_hash == private_token_hash(new_token)
    assert new_token != stored_hash
    assert new_token not in caplog.text


def test_cli_created_admin_can_log_in_with_same_email_validation(client):
    email = f"cli+{uuid.uuid4().hex}@example.com"
    password = "CLI password long enough 2026"
    result = subprocess.run(
        [sys.executable, "-m", "cli", "create-admin", "--email", email.upper(), "--name", "CLI", "--password-stdin"],
        cwd=BACKEND_DIR,
        env=os.environ.copy(),
        input=password + "\n",
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert password not in result.stdout + result.stderr
    response = client.post(
        "/api/v1/auth/login",
        json={"email": f"  {email.upper()}  ", "password": password},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200, response.text


def test_production_catalog_seed_is_atomic_idempotent_and_private_free(tmp_path):
    database = tmp_path / "catalog.db"
    env = os.environ.copy()
    env.update(
        {
            "ENVIRONMENT": "test",
            "DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}",
            "AUTO_MIGRATE": "false",
            "LOAD_SEED_DATA": "false",
            "APP_DEBUG": "false",
        }
    )
    command = [sys.executable, "-m", "cli", "init-catalog"]
    first = subprocess.run(command, cwd=BACKEND_DIR, env=env, text=True, capture_output=True, timeout=60, check=False)
    second = subprocess.run(command, cwd=BACKEND_DIR, env=env, text=True, capture_output=True, timeout=60, check=False)
    assert first.returncode == second.returncode == 0, first.stderr + second.stderr

    with sqlite3.connect(database) as db:
        counts = {
            table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in (
                "categories",
                "delivery_points",
                "store_settings",
                "products",
                "delivery_slots",
                "product_variants",
                "product_images",
            )
        }
        assert all(count > 0 for count in counts.values())
        assert db.execute("SELECT COUNT(*) FROM private_settings").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM admin_accounts").fetchone()[0] == 0
        assert "012180001234567895" not in str(db.execute("SELECT * FROM store_settings").fetchall())
        db.execute("DELETE FROM product_images")
        db.commit()

    partial = subprocess.run(command, cwd=BACKEND_DIR, env=env, text=True, capture_output=True, timeout=60, check=False)
    assert partial.returncode != 0
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM product_images").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == counts["products"]


def test_email_network_error_is_logged_as_failed_and_does_not_stop_other_emails(client, monkeypatch):
    import httpx

    async def unreachable_provider(self, *args, **kwargs):
        raise httpx.ConnectTimeout("simulated timeout")

    monkeypatch.setattr(mailer.app_settings, "resend_api_key", "test-provider-key")
    monkeypatch.setattr(httpx.AsyncClient, "post", unreachable_provider)

    created, _payload = create_reservation(client)

    with db_connection() as db:
        rows = db.execute(
            "SELECT n.template, n.status, n.error_message FROM notifications n "
            "JOIN reservations r ON r.id = n.reservation_id WHERE r.folio=?",
            (created["folio"],),
        ).fetchall()
    templates = {row["template"] for row in rows}
    assert {mailer.TEMPLATE_RECEIVED, mailer.TEMPLATE_BUSINESS_ALERT} <= templates
    assert all(row["status"] == "fallido" for row in rows)
    assert all("Resend" in row["error_message"] for row in rows)
