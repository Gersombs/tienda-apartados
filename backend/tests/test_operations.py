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


def test_admin_shell_installs_as_its_own_app(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(f"<head>{frontend_module.DEFAULT_MANIFEST}</head>", encoding="utf-8")
    (dist / "admin.webmanifest").write_text('{"name": "Nébula Beauty MX · Admin"}', encoding="utf-8")
    monkeypatch.setattr(frontend_module, "DIST_DIR", dist.resolve())

    admin = frontend_module.serve_frontend("/admin").body.decode()
    shop = frontend_module.serve_frontend("/catalogo", "Ana").body.decode()
    manifest = frontend_module.serve_frontend("/admin.webmanifest", 'Ana "B"').body.decode()

    assert 'href="/admin.webmanifest"' in admin and "/site.webmanifest" not in admin
    assert 'href="/site.webmanifest"' in shop and "admin" not in shop
    assert json.loads(manifest) == {"name": 'Ana "B" · Admin'}


def test_spa_shell_applies_only_known_palettes(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        f'<html lang="es-MX"><head>{frontend_module.DEFAULT_THEME_COLOR}</head></html>', encoding="utf-8"
    )
    monkeypatch.setattr(frontend_module, "DIST_DIR", dist.resolve())

    page = frontend_module.serve_frontend("/", None, "nude").body.decode()
    assert '<html data-paleta="nude" lang="es-MX">' in page and 'content="#A35533"' in page
    # Una paleta desconocida no se escribe en el HTML: se sirve el archivo tal cual.
    injected = frontend_module.serve_frontend("/", None, '"><script>')
    assert Path(injected.path) == dist / "index.html"
    # El hero se precarga sólo en la portada y sólo si es una ruta propia.
    hero = frontend_module.serve_frontend("/", None, None, '/api/v1/shop/images/3').body.decode()
    assert '<link rel="preload" as="image" fetchpriority="high" href="/api/v1/shop/images/3" />' in hero
    for path, url in [("/catalogo", "/images/x.webp"), ("/", "//evil.example/x"), ("/", "https://evil.example/x")]:
        assert Path(frontend_module.serve_frontend(path, None, None, url).path) == dist / "index.html"

    css = (BACKEND_DIR.parent / "frontend" / "src" / "index.css").read_text(encoding="utf-8")
    assert all(f"[data-paleta='{key}']" in css for key in frontend_module.PALETTES if key != "cereza")


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


def test_single_piece_variant_has_no_name_and_never_mixes_with_named_ones(client):
    headers = {"X-CSRF-Token": login(client)}
    slug = f"pieza-{uuid.uuid4().hex[:8]}"
    product = client.post(
        "/api/v1/crm/products", json={"name": "Pieza única", "slug": slug, "price": 100}, headers=headers
    )
    assert product.status_code == 200, product.text
    product_id = product.json()["id"]
    single = {"product_id": product_id, "option_name": "", "option_value": "", "stock": 2}
    named = {"product_id": product_id, "option_name": "Tono", "option_value": "Rojo", "stock": 1}

    created = client.post("/api/v1/crm/variants", json=single, headers=headers)
    assert created.status_code == 200, created.text
    with db_connection() as db:
        row = db.execute(
            "SELECT option_name, option_value, stock FROM product_variants WHERE id=?", (created.json()["id"],)
        ).fetchone()
    assert tuple(row) == ("", "", 2)

    mixed = client.post("/api/v1/crm/variants", json=named, headers=headers)
    assert mixed.status_code == 400
    assert "pieza única" in mixed.json()["detail"]

    assert client.delete(f"/api/v1/crm/variants/{created.json()['id']}", headers=headers).status_code == 200
    assert client.post("/api/v1/crm/variants", json=named, headers=headers).status_code == 200
    second_single = client.post("/api/v1/crm/variants", json=single, headers=headers)
    assert second_single.status_code == 400


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


def test_changing_product_price_keeps_variant_own_prices(client):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    product = {"name": "Crema prueba precio", "slug": "crema-prueba-precio", "price": 200}
    product_id = client.post("/api/v1/crm/products", json=product, headers=headers).json()["id"]
    for value, delta in (("50 ml", 50), ("30 ml", 0), ("10 ml", -50)):
        created = client.post(
            "/api/v1/crm/variants",
            json={"product_id": product_id, "option_name": "Tamaño", "option_value": value, "stock": 2, "price_delta": delta},
            headers=headers,
        )
        assert created.status_code == 200, created.text

    # Bajar el producto a $40 ya no deja la de $150 en -$10.
    assert client.put(f"/api/v1/crm/products/{product_id}", json={**product, "price": 40}, headers=headers).status_code == 200
    variants = client.get("/api/v1/shop/products/crema-prueba-precio").json()["product"]["variants"]
    assert {v["option_value"]: v["price"] for v in variants} == {"50 ml": 250, "30 ml": 40, "10 ml": 150}

    for bad_price in (0, -5):
        rejected = client.put(
            f"/api/v1/crm/products/{product_id}", json={**product, "price": bad_price}, headers=headers
        )
        assert rejected.status_code == 422
    assert client.delete(f"/api/v1/crm/products/{product_id}", headers=headers).status_code == 200


def test_social_links_always_leave_the_store():
    assert crm_router.social_url("@nathaly.makeup", "https://instagram.com/") == "https://instagram.com/nathaly.makeup"
    assert crm_router.social_url("@nathaly", "https://tiktok.com/@") == "https://tiktok.com/@nathaly"
    assert crm_router.social_url("instagram.com/nathaly", "https://instagram.com/") == "https://instagram.com/nathaly"
    assert crm_router.social_url("https://facebook.com/nathaly", "https://facebook.com/") == "https://facebook.com/nathaly"
    assert crm_router.social_url("javascript:alert(1)", "https://instagram.com/").startswith("https://")
    assert crm_router.social_url("  ", "https://instagram.com/") == ""


def test_catalog_card_shows_the_cheapest_variant_price(client):
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    product = {"name": "Perfume prueba desde", "slug": "perfume-prueba-desde", "price": 200}
    product_id = client.post("/api/v1/crm/products", json=product, headers=headers).json()["id"]
    for value, delta in (("50 ml", 50), ("100 ml", 200)):
        client.post(
            "/api/v1/crm/variants",
            json={"product_id": product_id, "option_name": "Tamaño", "option_value": value, "stock": 1, "price_delta": delta},
            headers=headers,
        )
    items = client.get("/api/v1/shop/products", params={"search": "perfume prueba desde"}).json()["items"]
    assert [(i["price"], i["price_varies"]) for i in items] == [(250, True)]
    # El filtro por precio usa el mismo precio que se ve en la tarjeta.
    assert client.get("/api/v1/shop/products", params={"search": "perfume prueba desde", "max_price": 220}).json()["items"] == []
    assert client.delete(f"/api/v1/crm/products/{product_id}", headers=headers).status_code == 200


def test_emails_write_the_delivery_date_in_spanish():
    assert mailer._fecha("2026-10-14") == "miércoles 14 de octubre"
    assert mailer._fecha("2027-01-03") == "domingo 3 de enero"
    assert mailer._fecha("no-es-fecha") == "no-es-fecha"


def test_settings_read_by_the_panel_can_be_saved_back_unchanged(client):
    csrf = login(client)
    store = client.get("/api/v1/crm/settings").json()["store"]
    saved = client.put("/api/v1/crm/settings/store", json=store, headers={"X-CSRF-Token": csrf})
    assert saved.status_code == 200, saved.text
    assert client.get("/api/v1/crm/settings").json()["store"] == store


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


def test_same_point_day_and_start_time_cannot_be_repeated(client):
    headers = {"X-CSRF-Token": login(client)}
    with db_connection() as db:
        point_id = db.execute("SELECT id FROM delivery_points LIMIT 1").fetchone()[0]
    slot = {"delivery_point_id": point_id, "weekday": 2, "start_time": "03:15", "end_time": "04:00", "capacity": 2}
    first = client.post("/api/v1/crm/delivery-slots", json=slot, headers=headers)
    assert first.status_code == 200, first.text
    other = client.post(
        "/api/v1/crm/delivery-slots", json={**slot, "start_time": "04:15", "end_time": "05:00"}, headers=headers
    )
    assert other.status_code == 200, other.text
    try:
        repeated = client.post("/api/v1/crm/delivery-slots", json={**slot, "end_time": "05:00"}, headers=headers)
        assert repeated.status_code == 400
        assert "ya existe" in repeated.json()["detail"]
        moved = client.put(
            f"/api/v1/crm/delivery-slots/{other.json()['id']}", json={**slot, "capacity": 5}, headers=headers
        )
        assert moved.status_code == 400
        # Guardar el mismo horario (por ejemplo, sólo cambiar el cupo) sigue funcionando.
        kept = client.put(
            f"/api/v1/crm/delivery-slots/{first.json()['id']}", json={**slot, "capacity": 5}, headers=headers
        )
        assert kept.status_code == 200, kept.text
    finally:
        for created in (first, other):
            client.delete(f"/api/v1/crm/delivery-slots/{created.json()['id']}", headers=headers)


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
            # En Windows el pipe usaría cp1252 de un lado y UTF-8 del otro; la "ñ" de la contraseña lo rompe.
            "PYTHONIOENCODING": "utf-8",
        }
    )
    command = [
        sys.executable, "-m", "cli", "nueva-tienda",
        "--nombre", "Luna Cosméticos", "--email", "Luna@Example.com",
        "--whatsapp", "55 1234 5678", "--password-stdin",
    ]
    run = lambda: subprocess.run(  # noqa: E731
        command, cwd=BACKEND_DIR, env=env, input="contraseña muy segura\n",
        text=True, encoding="utf-8", capture_output=True, timeout=60, check=False,
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
        # Así quedaban los textos guardados antes de conservar los saltos de línea.
        db.execute("UPDATE store_settings SET how_it_works=replace(how_it_works, char(10), ' ')")
        db.commit()

    def restore(*flags):
        return subprocess.run(
            [sys.executable, "-m", "cli", "restaurar-textos", *flags],
            cwd=BACKEND_DIR, env=env, text=True, encoding="utf-8", capture_output=True, timeout=60, check=False,
        )

    preview = restore()
    assert preview.returncode == 0 and "how_it_works" in preview.stdout and "faq_content" not in preview.stdout
    with sqlite3.connect(database) as db:
        assert "\n" not in db.execute("SELECT how_it_works FROM store_settings").fetchone()[0]
    assert restore("--aplicar").returncode == 0
    with sqlite3.connect(database) as db:
        assert "\n" in db.execute("SELECT how_it_works FROM store_settings").fetchone()[0]
    assert "ya están al día" in restore().stdout


def test_new_store_rejects_short_password_before_touching_the_database(tmp_path):
    database = tmp_path / "corta.db"
    env = os.environ.copy()
    # PYTHONIOENCODING: en una consola cp1252 de Windows el error con "ñ" no se podría leer.
    env.update({"ENVIRONMENT": "test", "DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}", "PYTHONIOENCODING": "utf-8"})
    result = subprocess.run(
        [sys.executable, "-m", "cli", "nueva-tienda", "--nombre", "X", "--email", "x@example.com", "--password-stdin"],
        cwd=BACKEND_DIR, env=env, input="corta\n", text=True, encoding="utf-8", capture_output=True, timeout=60, check=False,
    )
    assert result.returncode != 0
    assert "12 caracteres" in result.stderr
    assert not database.exists()


def test_unused_photo_cleanup_keeps_every_referenced_or_recent_photo(client):
    import asyncio
    from datetime import timedelta

    from sqlalchemy import delete, update
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from cli import unused_image_ids
    from core.time_utils import utc_now
    from models.categories import Categories
    from models.reservation_items import Reservation_items
    from models.uploaded_images import Uploaded_images

    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{TEST_DB.as_posix()}")
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                old = utc_now() - timedelta(days=3)
                photos = [
                    Uploaded_images(content_type="image/webp", size_bytes=1, data=b"x", created_at=created)
                    for created in (old, old, old, utc_now())
                ]
                db.add_all(photos)
                await db.commit()
                in_category, in_old_reservation, unused, fresh = (photo.id for photo in photos)
                await db.execute(
                    update(Categories)
                    .where(Categories.id == _category_id())
                    .values(image_url=f"/api/v1/shop/images/{in_category}")
                )
                await db.execute(
                    update(Reservation_items)
                    .where(Reservation_items.id == _reservation_item_id())
                    .values(image_url=f"/api/v1/shop/images/{in_old_reservation}")
                )
                await db.commit()
                found = await unused_image_ids(db)
                await db.execute(delete(Uploaded_images).where(Uploaded_images.id.in_([p.id for p in photos])))
                await db.commit()
                return found, in_category, in_old_reservation, unused, fresh
        finally:
            await engine.dispose()

    create_reservation(client)
    found, in_category, in_old_reservation, unused, fresh = asyncio.run(scenario())
    assert unused in found
    assert {in_category, in_old_reservation, fresh}.isdisjoint(found)


def _category_id() -> int:
    with db_connection() as db:
        return int(db.execute("SELECT id FROM categories ORDER BY id LIMIT 1").fetchone()[0])


def _reservation_item_id() -> int:
    with db_connection() as db:
        return int(db.execute("SELECT id FROM reservation_items ORDER BY id DESC LIMIT 1").fetchone()[0])


def test_long_texts_keep_their_line_breaks(client):
    from services.reservation_engine import sanitize_multiline

    assert sanitize_multiline("  Paso 1 \r\nPaso 2\n\n\n\nNota\x07  final  ") == "Paso 1\nPaso 2\n\nNota final"
    headers = {"X-CSRF-Token": login(client)}
    product_id = _product_id()
    with db_connection() as db:
        row = dict(db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
    body = {key: row[key] for key in ("name", "slug", "price", "category_id", "short_description", "ingredients")}
    body["full_description"] = "Textura cremosa.\n\nDura todo el día."
    saved = client.put(f"/api/v1/crm/products/{product_id}", json=body, headers=headers)
    assert saved.status_code == 200, saved.text
    detail = client.get(f"/api/v1/shop/products/{row['slug']}").json()["product"]
    assert detail["full_description"] == "Textura cremosa.\n\nDura todo el día."


def test_confirmation_gives_the_map_an_address_without_repeating_the_city(client):
    created, _payload = create_reservation(client)
    with db_connection() as db:
        db.execute(
            "UPDATE delivery_points SET address = 'Av. Insurgentes Sur 300, Roma Nte., Ciudad de México, CDMX',"
            " city = 'Ciudad de México' WHERE id = (SELECT delivery_point_id FROM reservations WHERE folio = ?)",
            (created["folio"],),
        )
        db.commit()
    reservation = client.post(
        "/api/v1/shop/confirmation", json={"token": created["private_token"]}
    ).json()["reservation"]
    assert reservation["delivery_point_address"] == "Av. Insurgentes Sur 300, Roma Nte., Ciudad de México, CDMX"


def test_calendar_file_comes_from_the_saved_reservation_not_from_the_link(client):
    created, _payload = create_reservation(client)
    with db_connection() as db:
        day, start, end = db.execute(
            "SELECT delivery_date, slot_start, slot_end FROM reservations WHERE folio = ?", (created["folio"],)
        ).fetchone()
    url = client.post("/api/v1/shop/confirmation", json={"token": created["private_token"]}).json()["reservation"]["calendar_url"]
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    lines = response.text.split("\r\n")
    # 10:00 en CDMX (UTC-6) es 16:00 UTC.
    utc = lambda hhmm: f"{day.replace('-', '')}T{int(hhmm[:2]) + 6:02d}{hhmm[3:5]}00Z"
    assert f"DTSTART:{utc(start)}" in lines and f"DTEND:{utc(end)}" in lines
    assert any(line.startswith("SUMMARY:Recoger mi apartado " + created["folio"]) for line in lines)

    # Un enlace armado a mano (otro folio, sin la firma o con texto propio) no sirve.
    assert client.get("/api/v1/shop/calendar.ics", params={"folio": created["folio"], "key": "x" * 32}).status_code == 404
    forged = client.get(url + "&title=Transfiere%20a%20la%20CLABE%20012")
    assert "CLABE" not in forged.text


def test_address_suggestions_come_from_google_without_exposing_the_key(client, monkeypatch):
    import httpx
    from core.config import settings

    login(client)
    assert client.get("/api/v1/crm/address-suggestions", params={"q": "Metro Insur"}).json() == {"suggestions": []}

    sent = {}

    async def fake_post(_self, url, headers=None, json=None):
        sent.update(url=url, headers=headers, body=json)
        return httpx.Response(
            200,
            json={"suggestions": [{"placePrediction": {"text": {"text": "Metro Insurgentes, Roma Nte., CDMX, México"}}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(settings, "google_maps_api_key", "clave-secreta-de-prueba")
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = client.get("/api/v1/crm/address-suggestions", params={"q": "Metro Insur"})
    assert response.json() == {"suggestions": ["Metro Insurgentes, Roma Nte., CDMX, México"]}
    assert sent["headers"]["X-Goog-Api-Key"] == "clave-secreta-de-prueba"
    assert sent["body"]["includedRegionCodes"] == ["mx"]
    assert "clave-secreta" not in response.text
