from __future__ import annotations

import concurrent.futures
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from conftest import create_reservation, db_connection, login, reservation_payload
from services.reservation_engine import (
    EXPIRATION_ALERT,
    EXPIRATION_ALERT_MARKER,
    parse_iso,
)


def test_unique_slugs_and_foreign_keys_are_enforced(client):
    with db_connection() as db:
        existing = db.execute("SELECT slug FROM products LIMIT 1").fetchone()["slug"]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO products (name, slug, price, is_active, is_featured, is_archived, sort_order) VALUES ('Duplicado', ?, 1, 1, 0, 0, 0)", (existing,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """
                INSERT INTO reservation_items
                    (reservation_id, product_name, unit_price, quantity, line_total)
                VALUES (999999, 'Huérfano', 10, 1, 10)
                """
            )


def test_folio_and_private_token_hash_are_unique(client):
    created, _payload = create_reservation(client)
    with db_connection() as db:
        row = db.execute(
            "SELECT folio, private_token_hash FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()
        statement = """
            INSERT INTO reservations
                (folio, private_token_hash, token_revoked, status, total_amount, item_count,
                 is_unread, privacy_accepted, stock_released)
            VALUES (?, ?, 0, 'recibida', 1, 1, 1, 1, 0)
        """
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(statement, (row["folio"], uuid.uuid4().hex + uuid.uuid4().hex))
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(statement, (f"AP-TEST-{uuid.uuid4().hex[:8]}", row["private_token_hash"]))


def test_creation_preserves_product_and_price_snapshots(client):
    created, payload = create_reservation(client)
    with db_connection() as db:
        reservation = db.execute("SELECT id, total_amount FROM reservations WHERE folio=?", (created["folio"],)).fetchone()
        item = db.execute(
            "SELECT product_name, variant_label, unit_price, quantity, line_total FROM reservation_items WHERE reservation_id=?",
            (reservation["id"],),
        ).fetchone()
    assert item["product_name"]
    assert item["variant_label"]
    assert item["unit_price"] >= 0
    assert item["line_total"] == pytest.approx(item["unit_price"] * item["quantity"])
    assert reservation["total_amount"] == pytest.approx(item["line_total"])


def test_cancellation_releases_once_and_delivery_consumes_once(client):
    csrf = login(client)
    created, payload = create_reservation(client)
    variant_id = payload["items"][0]["variant_id"]
    with db_connection() as db:
        reservation = db.execute("SELECT id FROM reservations WHERE folio=?", (created["folio"],)).fetchone()
        before = db.execute("SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)).fetchone()[0]
    headers = {"X-CSRF-Token": csrf}
    cancelled = client.post(
        f"/api/v1/crm/reservations/{reservation['id']}/status",
        json={"status": "cancelada", "note": "Prueba"},
        headers=headers,
    )
    repeated = client.post(
        f"/api/v1/crm/reservations/{reservation['id']}/status",
        json={"status": "cancelada", "note": "Prueba"},
        headers=headers,
    )
    assert cancelled.status_code == repeated.status_code == 200
    with db_connection() as db:
        after = db.execute("SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)).fetchone()[0]
        releases = db.execute(
            "SELECT COUNT(*) FROM inventory_movements WHERE reservation_id=? AND movement_type='liberacion'",
            (reservation["id"],),
        ).fetchone()[0]
    assert after == before - 1
    assert releases == 1

    delivered, delivered_payload = create_reservation(client)
    delivered_variant = delivered_payload["items"][0]["variant_id"]
    with db_connection() as db:
        delivered_id = db.execute("SELECT id FROM reservations WHERE folio=?", (delivered["folio"],)).fetchone()[0]
        stock_before = db.execute("SELECT stock FROM product_variants WHERE id=?", (delivered_variant,)).fetchone()[0]
    for status in ("lista", "entregada", "entregada"):
        response = client.post(
            f"/api/v1/crm/reservations/{delivered_id}/status",
            json={"status": status, "note": "Prueba"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
    with db_connection() as db:
        stock_after = db.execute("SELECT stock FROM product_variants WHERE id=?", (delivered_variant,)).fetchone()[0]
        outputs = db.execute(
            "SELECT COUNT(*) FROM inventory_movements WHERE reservation_id=? AND movement_type='salida'",
            (delivered_id,),
        ).fetchone()[0]
    assert stock_after == stock_before - 1
    assert outputs == 1


def test_invalid_terminal_transition_returns_domain_error(client):
    csrf = login(client)
    created, _payload = create_reservation(client)
    with db_connection() as db:
        reservation_id = db.execute("SELECT id FROM reservations WHERE folio=?", (created["folio"],)).fetchone()[0]
    headers = {"X-CSRF-Token": csrf}
    assert client.post(
        f"/api/v1/crm/reservations/{reservation_id}/status",
        json={"status": "cancelada", "note": "Prueba"},
        headers=headers,
    ).status_code == 200
    invalid = client.post(
        f"/api/v1/crm/reservations/{reservation_id}/status",
        json={"status": "entregada", "note": "No permitido"},
        headers=headers,
    )
    assert invalid.status_code == 400


def test_expiration_releases_inventory_exactly_once(client):
    created, payload = create_reservation(client)
    variant_id = payload["items"][0]["variant_id"]
    with db_connection() as db:
        reservation = db.execute(
            "SELECT id FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()
        before = db.execute(
            "SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)
        ).fetchone()[0]
        expired_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.execute("UPDATE reservations SET expires_at=? WHERE id=?", (expired_at, reservation["id"]))
        db.commit()

    assert client.get("/api/v1/shop/bootstrap").status_code == 200
    assert client.get("/api/v1/shop/bootstrap").status_code == 200
    with db_connection() as db:
        after = db.execute(
            "SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)
        ).fetchone()[0]
        row = db.execute(
            "SELECT status, stock_released FROM reservations WHERE id=?", (reservation["id"],)
        ).fetchone()
        releases = db.execute(
            "SELECT COUNT(*) FROM inventory_movements WHERE reservation_id=? AND movement_type='liberacion'",
            (reservation["id"],),
        ).fetchone()[0]
    assert after == before - 1
    assert row["status"] == "vencida"
    assert row["stock_released"] == 1
    assert releases == 1


def test_expired_reservation_can_still_be_delivered_from_free_stock(client):
    headers = {"X-CSRF-Token": login(client)}
    with db_connection() as db:
        category_id = db.execute("SELECT id FROM categories LIMIT 1").fetchone()[0]
        product_id = db.execute(
            "INSERT INTO products (name, slug, category_id, price, is_active, is_featured, is_archived, sort_order) VALUES ('Entrega tardía', ?, ?, 50, 1, 0, 0, 999)",
            (f"tardia-{uuid.uuid4().hex}", category_id),
        ).lastrowid
        variant_id = db.execute(
            "INSERT INTO product_variants (product_id, option_name, option_value, stock, reserved_stock, price_delta, is_active) VALUES (?, '', '', 1, 0, 0, 1)",
            (product_id,),
        ).lastrowid
        db.commit()

    late, _ = create_reservation(client, variant_id=variant_id)
    with db_connection() as db:
        late_id = db.execute("SELECT id FROM reservations WHERE folio=?", (late["folio"],)).fetchone()[0]
        expired_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.execute("UPDATE reservations SET expires_at=? WHERE id=?", (expired_at, late_id))
        db.commit()
    assert client.get("/api/v1/shop/bootstrap").status_code == 200

    def deliver():
        return client.post(
            f"/api/v1/crm/reservations/{late_id}/status", json={"status": "entregada"}, headers=headers
        )

    def variant():
        with db_connection() as db:
            return tuple(db.execute(
                "SELECT stock, reserved_stock FROM product_variants WHERE id=?", (variant_id,)
            ).fetchone())

    # La pieza liberada se volvió a apartar: no se puede entregar dos veces la misma.
    other, _ = create_reservation(client, variant_id=variant_id)
    blocked = deliver()
    assert blocked.status_code == 400
    assert "Ajusta el inventario" in blocked.json()["detail"]
    assert variant() == (1, 1)

    with db_connection() as db:
        other_id = db.execute("SELECT id FROM reservations WHERE folio=?", (other["folio"],)).fetchone()[0]
    assert client.post(
        f"/api/v1/crm/reservations/{other_id}/status", json={"status": "cancelada"}, headers=headers
    ).status_code == 200

    assert deliver().status_code == 200
    assert deliver().status_code == 200  # repetir no descuenta otra vez
    assert variant() == (0, 0)
    with db_connection() as db:
        row = db.execute(
            "SELECT status, cancel_reason FROM reservations WHERE id=?", (late_id,)
        ).fetchone()
        outputs = db.execute(
            "SELECT COUNT(*) FROM inventory_movements WHERE reservation_id=? AND movement_type='salida'",
            (late_id,),
        ).fetchone()[0]
    assert row["status"] == "entregada"
    assert row["cancel_reason"] is None
    assert outputs == 1


def test_confirmation_expires_only_its_reservation_and_is_idempotent(client):
    created, payload = create_reservation(client)
    token = created["private_token"]
    variant_id = payload["items"][0]["variant_id"]
    with db_connection() as db:
        reservation_id = db.execute(
            "SELECT id FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()[0]
        before = db.execute(
            "SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)
        ).fetchone()[0]
        mexico_timezone = timezone(timedelta(hours=-6))
        expired_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).astimezone(mexico_timezone).isoformat()
        db.execute(
            "UPDATE reservations SET expires_at=? WHERE id=?", (expired_at, reservation_id)
        )
        db.commit()

    for _ in range(3):
        response = client.post("/api/v1/shop/confirmation", json={"token": token})
        assert response.status_code == 200
        assert response.json()["reservation"]["status"] == "vencida"
        assert not any(response.json()["bank_details"].values())

    with db_connection() as db:
        after = db.execute(
            "SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)
        ).fetchone()[0]
        releases = db.execute(
            "SELECT COUNT(*) FROM inventory_movements "
            "WHERE reservation_id=? AND movement_type='liberacion'",
            (reservation_id,),
        ).fetchone()[0]
        history = db.execute(
            "SELECT COUNT(*) FROM reservation_status_history "
            "WHERE reservation_id=? AND to_status='vencida'",
            (reservation_id,),
        ).fetchone()[0]
    assert after == before - 1
    assert releases == 1
    assert history == 1


@pytest.mark.parametrize(
    "canonical_expires_at",
    ["2026-08-28T18:00:00-06:00", "2026-08-29T00:00:00Z"],
)
def test_parse_iso_accepts_only_complete_zoned_canonical_examples(canonical_expires_at):
    parsed = parse_iso(canonical_expires_at)

    assert parsed is not None
    assert parsed.tzinfo is timezone.utc


def test_canonical_future_expiration_keeps_reservation_and_inventory(client):
    created, payload = create_reservation(client)
    token = created["private_token"]
    variant_id = payload["items"][0]["variant_id"]
    future = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with db_connection() as db:
        reservation_id = db.execute(
            "SELECT id FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()[0]
        before = db.execute(
            "SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)
        ).fetchone()[0]
        original_status = db.execute(
            "SELECT status FROM reservations WHERE id=?", (reservation_id,)
        ).fetchone()[0]
        db.execute(
            "UPDATE reservations SET expires_at=? WHERE id=?", (future, reservation_id)
        )
        db.commit()

    response = client.post("/api/v1/shop/confirmation", json={"token": token})
    assert response.status_code == 200
    assert response.json()["reservation"]["status"] == original_status

    with db_connection() as db:
        after = db.execute(
            "SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)
        ).fetchone()[0]
        releases = db.execute(
            "SELECT COUNT(*) FROM inventory_movements "
            "WHERE reservation_id=? AND movement_type='liberacion'",
            (reservation_id,),
        ).fetchone()[0]
    assert after == before
    assert releases == 0


@pytest.mark.parametrize(
    "broken_expires_at",
    [
        None,
        "",
        "   ",
        "not-an-iso-datetime",
        "2000-01-01",
        "2000-01-01T00:00:00",
        "2000-01-01 00:00:00+00:00",
        "2000-W01-1T00:00:00+00:00",
        "20000101T000000+0000",
        "2000-01-01T00:00:00+99:00",
        "2000-01-01T00:00:00+00:00 trailing",
    ],
)
def test_invalid_expiration_blocks_bank_details_without_releasing_stock(
    client, broken_expires_at
):
    created, payload = create_reservation(client)
    token = created["private_token"]
    variant_id = payload["items"][0]["variant_id"]
    with db_connection() as db:
        reservation_id = db.execute(
            "SELECT id FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()[0]
        before = db.execute(
            "SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)
        ).fetchone()[0]
        original = db.execute(
            "SELECT status, stock_released FROM reservations WHERE id=?", (reservation_id,)
        ).fetchone()
        db.execute(
            "UPDATE reservations SET expires_at=? WHERE id=?",
            (broken_expires_at, reservation_id),
        )
        db.commit()

    # The general sweep must surface the damaged record instead of ignoring it.
    for _ in range(3):
        assert client.get("/api/v1/shop/bootstrap").status_code == 200
    for _ in range(3):
        response = client.post("/api/v1/shop/confirmation", json={"token": token})
        assert response.status_code == 409
        assert "bank_details" not in response.json()
        assert response.headers["Cache-Control"] == "no-store"

    with db_connection() as db:
        after = db.execute(
            "SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)
        ).fetchone()[0]
        row = db.execute(
            "SELECT status, stock_released, internal_notes, is_unread "
            "FROM reservations WHERE id=?",
            (reservation_id,),
        ).fetchone()
        releases = db.execute(
            "SELECT COUNT(*) FROM inventory_movements "
            "WHERE reservation_id=? AND movement_type='liberacion'",
            (reservation_id,),
        ).fetchone()[0]
        history = db.execute(
            "SELECT COUNT(*) FROM reservation_status_history "
            "WHERE reservation_id=? AND to_status='vencida'",
            (reservation_id,),
        ).fetchone()[0]

    assert after == before
    assert row["status"] == original["status"]
    assert row["stock_released"] == original["stock_released"]
    assert releases == 0
    assert history == 0
    assert row["is_unread"] == 1
    assert row["internal_notes"].count(EXPIRATION_ALERT_MARKER) == 1

    login(client)
    detail = client.get(f"/api/v1/crm/reservations/{reservation_id}")
    assert detail.status_code == 200
    assert EXPIRATION_ALERT_MARKER in detail.json()["reservation"]["internal_notes"]


def test_expiration_alert_preserves_full_admin_note_and_survives_crm_save(client):
    created, _payload = create_reservation(client)
    original_notes = "N" * 2000
    with db_connection() as db:
        reservation_id = db.execute(
            "SELECT id FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()[0]
        db.execute(
            "UPDATE reservations SET expires_at=?, internal_notes=? WHERE id=?",
            ("2000-01-01", original_notes, reservation_id),
        )
        db.commit()

    for _ in range(3):
        assert client.get("/api/v1/shop/bootstrap").status_code == 200
    with db_connection() as db:
        stored = db.execute(
            "SELECT internal_notes, is_unread FROM reservations WHERE id=?",
            (reservation_id,),
        ).fetchone()
    assert stored["internal_notes"] == f"{original_notes}\n\n{EXPIRATION_ALERT}"
    assert stored["internal_notes"].count(EXPIRATION_ALERT_MARKER) == 1
    assert stored["is_unread"] == 1

    csrf = login(client)
    saved = client.post(
        f"/api/v1/crm/reservations/{reservation_id}/note",
        json={"internal_notes": stored["internal_notes"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200
    assert saved.json()["internal_notes"] == f"{original_notes}\n\n{EXPIRATION_ALERT}"
    assert saved.json()["internal_notes"].count(EXPIRATION_ALERT_MARKER) == 1

    replacement_notes = "R" * 2000
    replaced = client.post(
        f"/api/v1/crm/reservations/{reservation_id}/note",
        json={"internal_notes": replacement_notes},
        headers={"X-CSRF-Token": csrf},
    )
    assert replaced.status_code == 200
    assert replaced.json()["internal_notes"] == f"{replacement_notes}\n\n{EXPIRATION_ALERT}"


def test_two_requests_cannot_reserve_the_last_unit(client):
    slug = f"concurrencia-{uuid.uuid4().hex}"
    with db_connection() as db:
        category_id = db.execute("SELECT id FROM categories LIMIT 1").fetchone()[0]
        product_id = db.execute(
            "INSERT INTO products (name, slug, category_id, price, is_active, is_featured, is_archived, sort_order) VALUES (?, ?, ?, 99, 1, 0, 0, 999)",
            ("Producto concurrencia", slug, category_id),
        ).lastrowid
        variant_id = db.execute(
            "INSERT INTO product_variants (product_id, option_name, option_value, sku, stock, reserved_stock, price_delta, is_active) VALUES (?, 'Presentación', 'Única', ?, 1, 0, 0, 1)",
            (product_id, f"CON-{uuid.uuid4().hex}"),
        ).lastrowid
        db.commit()

    payloads = [
        reservation_payload(client, variant_id=variant_id, email=f"race-{index}-{uuid.uuid4().hex}@example.com")
        for index in range(2)
    ]

    def submit(payload):
        return client.post("/api/v1/shop/reservations", json=payload).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(submit, payloads))
    assert sorted(statuses) == [200, 400]
    with db_connection() as db:
        variant = db.execute("SELECT stock, reserved_stock FROM product_variants WHERE id=?", (variant_id,)).fetchone()
    assert variant["stock"] == 1
    assert variant["reserved_stock"] == 1


def test_slot_that_already_started_today_is_rejected(client):
    mexico_now = datetime.now(timezone(timedelta(hours=-6)))
    with db_connection() as db:
        point_id = db.execute(
            "SELECT id FROM delivery_points WHERE is_active=1 LIMIT 1"
        ).fetchone()[0]
        slot_id = db.execute(
            "INSERT INTO delivery_slots (delivery_point_id, weekday, start_time, end_time, capacity, is_active) "
            "VALUES (?, ?, '00:00', '00:01', 0, 1)",
            (point_id, mexico_now.weekday()),
        ).lastrowid
        db.commit()
    try:
        payload = reservation_payload(client)
        payload.update(
            delivery_point_id=point_id,
            delivery_date=mexico_now.date().isoformat(),
            slot_start="00:00",
        )
        response = client.post("/api/v1/shop/reservations", json=payload)
        assert response.status_code == 400
        assert "comenzó" in response.json()["detail"]
    finally:
        with db_connection() as db:
            db.execute("DELETE FROM delivery_slots WHERE id=?", (slot_id,))
            db.commit()


def test_admin_can_mark_invalid_expiration_alert_as_read(client):
    created, _payload = create_reservation(client)
    with db_connection() as db:
        reservation_id = db.execute(
            "SELECT id FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()[0]
        db.execute("UPDATE reservations SET expires_at=NULL WHERE id=?", (reservation_id,))
        db.commit()

    assert client.get("/api/v1/shop/bootstrap").status_code == 200
    csrf = login(client)
    marked = client.post(
        f"/api/v1/crm/reservations/{reservation_id}/read", headers={"X-CSRF-Token": csrf}
    )
    assert marked.status_code == 200
    client.cookies.clear()

    for _ in range(3):
        assert client.get("/api/v1/shop/bootstrap").status_code == 200
    with db_connection() as db:
        row = db.execute(
            "SELECT is_unread, internal_notes FROM reservations WHERE id=?", (reservation_id,)
        ).fetchone()
    assert row["is_unread"] == 0
    assert row["internal_notes"].count(EXPIRATION_ALERT_MARKER) == 1


def test_availability_keeps_line_order_and_flags_unknown_or_short_lines(client):
    variant_id = reservation_payload(client)["items"][0]["variant_id"]
    response = client.post(
        "/api/v1/shop/availability",
        json={"items": [
            {"variant_id": 999999, "quantity": 1},
            {"variant_id": variant_id, "quantity": 1},
        ]},
    )
    assert response.status_code == 200
    lines = response.json()["lines"]
    assert [line["variant_id"] for line in lines] == [999999, variant_id]
    assert lines[0]["ok"] is False
    assert lines[1]["ok"] is True
    assert lines[1]["product_name"]
    assert lines[1]["unit_price"] >= 0
    assert response.json()["all_ok"] is False


def test_zero_grace_hours_expires_right_when_the_slot_ends(client):
    with db_connection() as db:
        original = db.execute("SELECT grace_period_hours FROM store_settings ORDER BY id LIMIT 1").fetchone()[0]
        db.execute("UPDATE store_settings SET grace_period_hours=0")
        db.commit()
    try:
        created, payload = create_reservation(client)
        with db_connection() as db:
            row = db.execute(
                "SELECT expires_at, slot_end FROM reservations WHERE folio=?", (created["folio"],)
            ).fetchone()
    finally:
        with db_connection() as db:
            db.execute("UPDATE store_settings SET grace_period_hours=?", (original,))
            db.commit()
    expires = datetime.fromisoformat(row["expires_at"])
    assert expires.date().isoformat() == payload["delivery_date"]
    assert expires.strftime("%H:%M") == row["slot_end"]


def test_customer_can_cancel_with_her_link_and_store_sees_it_unread(client):
    created, payload = create_reservation(client)
    variant_id = payload["items"][0]["variant_id"]
    with db_connection() as db:
        reservation_id = db.execute("SELECT id FROM reservations WHERE folio=?", (created["folio"],)).fetchone()[0]
        db.execute("UPDATE reservations SET is_unread=0 WHERE id=?", (reservation_id,))
        db.commit()
        reserved_before = db.execute("SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)).fetchone()[0]
        emails_before = db.execute("SELECT COUNT(*) FROM notifications WHERE reservation_id=?", (reservation_id,)).fetchone()[0]

    cancelled = client.post("/api/v1/shop/confirmation/cancel", json={"token": created["private_token"]})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelada"
    again = client.post("/api/v1/shop/confirmation/cancel", json={"token": created["private_token"]})
    assert again.status_code == 409
    assert client.post("/api/v1/shop/confirmation/cancel", json={"token": "x" * 43}).status_code == 404

    with db_connection() as db:
        row = db.execute("SELECT status, is_unread, cancel_reason FROM reservations WHERE id=?", (reservation_id,)).fetchone()
        reserved_after = db.execute("SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)).fetchone()[0]
        emails_after = db.execute("SELECT COUNT(*) FROM notifications WHERE reservation_id=?", (reservation_id,)).fetchone()[0]
    assert (row["status"], row["is_unread"], row["cancel_reason"]) == ("cancelada", 1, "Cancelado por la clienta")
    assert reserved_after == reserved_before - 1
    assert emails_after == emails_before  # cancelar ella misma no gasta correos

    login(client)
    unread = client.get("/api/v1/crm/dashboard").json()["unread"]
    assert any(item["folio"] == created["folio"] for item in unread)


def test_only_cancellation_emails_the_customer_and_panel_offers_only_valid_changes(client):
    headers = {"X-CSRF-Token": login(client)}
    created, _payload = create_reservation(client)
    with db_connection() as db:
        reservation_id = db.execute("SELECT id FROM reservations WHERE folio=?", (created["folio"],)).fetchone()[0]

    def emails() -> int:
        with db_connection() as db:
            return db.execute("SELECT COUNT(*) FROM notifications WHERE reservation_id=?", (reservation_id,)).fetchone()[0]

    detail = client.get(f"/api/v1/crm/reservations/{reservation_id}").json()
    offered = [s["value"] for s in detail["statuses"]]
    assert "confirmada" not in offered and "entregada" in offered

    before = emails()
    for status in ("preparando", "lista"):
        assert client.post(
            f"/api/v1/crm/reservations/{reservation_id}/status", json={"status": status}, headers=headers
        ).status_code == 200
    assert emails() == before
    assert client.post(
        f"/api/v1/crm/reservations/{reservation_id}/status", json={"status": "cancelada"}, headers=headers
    ).status_code == 200
    assert emails() == before + 1
    assert client.get(f"/api/v1/crm/reservations/{reservation_id}").json()["statuses"] == []
