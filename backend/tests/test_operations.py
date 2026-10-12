from __future__ import annotations

import csv
import io
import json
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


def test_spa_shell_and_manifest_show_the_store_name(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<title>Nébula Beauty MX | Aparta</title><meta property="og:title" content="Nébula Beauty MX" />',
        encoding="utf-8",
    )
    (dist / "site.webmanifest").write_text(
        '{"name": "Nébula Beauty MX", "short_name": "Nébula Beauty"}', encoding="utf-8"
    )
    monkeypatch.setattr(frontend_module, "DIST_DIR", dist.resolve())

    page = frontend_module.serve_frontend("/catalogo", 'Ana "<b>"').body.decode()
    manifest = frontend_module.serve_frontend("/site.webmanifest", 'Ana "<b>"').body.decode()

    assert "Nébula" not in page and 'content="Ana &quot;&lt;b&gt;&quot;"' in page
    assert json.loads(manifest) == {"name": 'Ana "<b>"', "short_name": 'Ana "<b>"'}


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


def test_variants_without_sku_coexist_and_duplicate_sku_is_a_clear_error(client):
    headers = {"X-CSRF-Token": login(client)}
    product_id = _product_id()
    sku = f"DUP-{uuid.uuid4().hex}"

    def create(value: str, sku_value: str):
        return client.post(
            "/api/v1/crm/variants",
            json={"product_id": product_id, "option_name": "Tono", "option_value": value, "sku": sku_value},
            headers=headers,
        )

    assert create("Sin SKU 1", "").status_code == 200
    second = create("Sin SKU 2", "  ")
    assert second.status_code == 200, second.text
    assert create("Con SKU", sku).status_code == 200
    duplicate = create("Repetido", sku)
    assert duplicate.status_code == 400 and "SKU" in duplicate.json()["detail"]
    edit = client.put(
        f"/api/v1/crm/variants/{second.json()['id']}",
        json={"product_id": product_id, "option_name": "Tono", "option_value": "Sin SKU 2", "sku": sku},
        headers=headers,
    )
    assert edit.status_code == 400


def test_single_piece_variant_has_no_name_or_label(client):
    headers = {"X-CSRF-Token": login(client)}
    created = client.post(
        "/api/v1/crm/variants",
        json={"product_id": _product_id(), "option_name": "", "option_value": "", "stock": 2},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    with db_connection() as db:
        row = db.execute(
            "SELECT option_name, option_value, stock FROM product_variants WHERE id=?", (created.json()["id"],)
        ).fetchone()
    assert tuple(row) == ("", "", 2)


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

    async def successful_provider(_api_key, _sender, _to, _subject, html, reply_to=""):
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

    async def failed_provider(_api_key, _sender, _to, _subject, _html, reply_to=""):
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


def test_unreachable_provider_is_tried_once_and_every_email_is_logged_failed(client, monkeypatch):
    import httpx

    calls = []

    async def unreachable_provider(self, *args, **kwargs):
        calls.append(kwargs.get("json"))
        raise httpx.ConnectTimeout("simulated timeout")

    monkeypatch.setattr(mailer.app_settings, "resend_api_key", "test-provider-key")
    monkeypatch.setattr(httpx.AsyncClient, "post", unreachable_provider)

    created, _payload = create_reservation(client)
    assert len(calls) == 1

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


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_admin_uploads_photo_and_public_can_fetch_it(client):
    anonymous = client.post("/api/v1/crm/uploads", content=PNG_BYTES)
    assert anonymous.status_code == 401

    csrf = login(client)
    headers = {"X-CSRF-Token": csrf, "Content-Type": "application/octet-stream"}
    without_csrf = client.post(
        "/api/v1/crm/uploads", content=PNG_BYTES, headers={"Content-Type": "image/png"}
    )
    assert without_csrf.status_code == 403

    uploaded = client.post("/api/v1/crm/uploads", content=PNG_BYTES, headers=headers)
    assert uploaded.status_code == 200, uploaded.text
    url = uploaded.json()["url"]

    client.cookies.clear()
    image = client.get(url)
    assert image.status_code == 200
    assert image.content == PNG_BYTES
    assert image.headers["content-type"] == "image/png"
    assert "immutable" in image.headers["cache-control"]
    assert client.get("/api/v1/shop/images/999999").status_code == 404


def test_upload_rejects_non_images_and_oversized_files(client):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    svg = client.post("/api/v1/crm/uploads", content=b"<svg onload=alert(1)>", headers=headers)
    assert svg.status_code == 400
    huge = client.post(
        "/api/v1/crm/uploads",
        content=PNG_BYTES + b"\x00" * (crm_router.MAX_UPLOAD_BYTES + 1),
        headers=headers,
    )
    assert huge.status_code == 413


def test_editing_variant_details_keeps_current_stock(client):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    product_id = _product_id()
    created = client.post(
        "/api/v1/crm/variants",
        json={"product_id": product_id, "option_name": "Tono", "option_value": "Rosa", "stock": 4},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    variant_id = created.json()["id"]
    with db_connection() as db:
        db.execute("UPDATE product_variants SET stock=3 WHERE id=?", (variant_id,))
        db.commit()

    renamed = client.put(
        f"/api/v1/crm/variants/{variant_id}",
        json={"product_id": product_id, "option_name": "Tono", "option_value": "Rosa palo"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["stock"] == 3
    assert client.delete(f"/api/v1/crm/variants/{variant_id}", headers=headers).status_code == 200


def test_slot_times_must_be_zero_padded_hours(client):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    with db_connection() as db:
        point_id = db.execute("SELECT id FROM delivery_points LIMIT 1").fetchone()[0]
    bad = client.post(
        "/api/v1/crm/delivery-slots",
        json={"delivery_point_id": point_id, "weekday": 1, "start_time": "9:00", "end_time": "10:00"},
        headers=headers,
    )
    assert bad.status_code == 422
    good = client.post(
        "/api/v1/crm/delivery-slots",
        json={"delivery_point_id": point_id, "weekday": 1, "start_time": "09:00", "end_time": "10:00"},
        headers=headers,
    )
    assert good.status_code == 200, good.text
    assert client.delete(f"/api/v1/crm/delivery-slots/{good.json()['id']}", headers=headers).status_code == 200


def test_emails_use_operator_sender_and_reply_to_the_right_person(client, monkeypatch):
    import httpx

    sent = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": "msg-test"}

    async def capturing_provider(self, *args, **kwargs):
        sent.append(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr(mailer.app_settings, "resend_api_key", "test-provider-key")
    monkeypatch.setattr(mailer.app_settings, "email_from_address", "avisos@operador.mx")
    monkeypatch.setattr(httpx.AsyncClient, "post", capturing_provider)

    created, payload = create_reservation(client)

    with db_connection() as db:
        contact = db.execute("SELECT contact_email FROM store_settings LIMIT 1").fetchone()[0]
    customer = next(body for body in sent if body["to"] == [payload["email"]])
    business = next(body for body in sent if body["to"] != [payload["email"]])
    assert all(body["from"].endswith("<avisos@operador.mx>") for body in sent)
    assert customer.get("reply_to", "") == (contact or "")
    assert business["reply_to"] == payload["email"]


def test_new_store_is_blank_branded_and_has_its_admin(tmp_path):
    database = tmp_path / "tienda.db"
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
    command = [
        sys.executable, "-m", "cli", "nueva-tienda",
        "--nombre", "Luna Cosméticos", "--email", "Luna@Example.com",
        "--whatsapp", "55 1234 5678", "--password-stdin",
    ]
    run = lambda: subprocess.run(  # noqa: E731
        command, cwd=BACKEND_DIR, env=env, input="contraseña muy segura\n",
        text=True, capture_output=True, timeout=60, check=False,
    )
    first, second = run(), run()
    assert first.returncode == 0, first.stderr
    assert "Tienda creada" in first.stdout
    assert second.returncode == 0 and "no se modificó" in second.stdout

    with sqlite3.connect(database) as db:
        settings = db.execute(
            "SELECT shop_name, contact_email, contact_whatsapp, logo_url, how_it_works, privacy_policy "
            "FROM store_settings"
        ).fetchall()
        assert len(settings) == 1
        shop_name, contact, whatsapp, logo, how_it_works, privacy = settings[0]
        assert (shop_name, contact, whatsapp, logo) == ("Luna Cosméticos", "luna@example.com", "5512345678", "")
        assert how_it_works and "Nébula" not in privacy and "Luna Cosméticos" in privacy
        for table in ("categories", "products", "product_variants", "delivery_points", "delivery_slots", "private_settings"):
            assert db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0, table
        assert db.execute(
            "SELECT COUNT(*) FROM admin_accounts WHERE normalized_email='luna@example.com'"
        ).fetchone()[0] == 1


def test_new_store_rejects_short_password_before_touching_the_database(tmp_path):
    database = tmp_path / "corta.db"
    env = os.environ.copy()
    env.update({"ENVIRONMENT": "test", "DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}"})
    result = subprocess.run(
        [sys.executable, "-m", "cli", "nueva-tienda", "--nombre", "X", "--email", "x@example.com", "--password-stdin"],
        cwd=BACKEND_DIR, env=env, input="corta\n", text=True, capture_output=True, timeout=60, check=False,
    )
    assert result.returncode != 0
    assert "12 caracteres" in result.stderr
    assert not database.exists()
