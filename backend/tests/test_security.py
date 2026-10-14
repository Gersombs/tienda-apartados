from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from core.auth import hash_password, private_token_hash
from core.config import Settings, settings
from core.reservation_limits import MAX_RESERVATION_BODY_BYTES, MAX_RESERVATION_TOTAL_UNITS
from main import PROTECTED_AUTH_ENDPOINTS, PUBLIC_ENDPOINTS, app, is_public_request
from routers.auth import GENERIC_LOGIN_ERROR, LoginRateLimiter, login_limiter
from schemas.shop import ReservationPublicCreate

from conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    create_reservation,
    db_connection,
    login,
    reservation_payload,
)


SENSITIVE_CONFIRMATION_FIELDS = {
    "id",
    "customer_id",
    "customer_email",
    "customer_whatsapp",
    "customer_notes",
    "internal_notes",
    "client_fingerprint",
    "private_token",
    "private_token_hash",
    "is_unread",
}


def _concrete_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def _openapi_operations() -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for path, path_item in app.openapi()["paths"].items():
        for method in path_item:
            if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                operations.add((method.upper(), path))
    return operations


def test_registered_surface_is_explicit_and_has_no_generated_crud(client):
    live = _openapi_operations()
    assert (PUBLIC_ENDPOINTS - {("GET", "/health")}) <= live
    assert client.get("/health").status_code == 200
    assert PROTECTED_AUTH_ENDPOINTS <= live
    assert is_public_request("GET", "/api/v1/shop/products/example-slug")
    assert not is_public_request("DELETE", "/api/v1/shop/products/example-slug")
    assert all("/entities/" not in path for _method, path in live)
    assert ("POST", "/api/v1/crm/claim-admin") not in live
    forbidden_prefixes = tuple(f"/api/v1/{suffix}" for suffix in ("storage", "aihub", "admin/settings"))
    assert all(not path.startswith(forbidden_prefixes) for _, path in live)
    assert client.get("/api/v1/future-route-added-by-mistake").status_code == 404


def test_no_http_method_can_create_or_escalate_an_admin(client):
    csrf = login(client)
    response = client.post(
        "/api/v1/crm/admins",
        json={"email": "attacker@example.com", "role": "admin", "is_active": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 405
    assert not any(path.startswith("/api/v1/crm/admins") for _method, path in _openapi_operations())


def test_every_admin_route_rejects_anonymous_before_dispatch(client):
    admin_operations = sorted(
        (method, path) for method, path in _openapi_operations() if path.startswith("/api/v1/crm")
    )
    assert admin_operations
    for method, path in admin_operations:
        kwargs = {} if method == "GET" else {"json": {}}
        response = client.request(method, _concrete_path(path), **kwargs)
        assert response.status_code == 401, (method, path, response.status_code, response.text)


def test_public_catalog_has_only_allowlisted_fields(client):
    response = client.get("/api/v1/shop/products")
    assert response.status_code == 200
    product = response.json()["items"][0]
    assert not {
        "id",
        "category_id",
        "is_archived",
        "sort_order",
        "updated_at",
        "created_at",
        "internal_notes",
    } & product.keys()
    assert "stock" not in str(product).lower()
    assert "clabe" not in response.text.lower()

    detail = client.get(f"/api/v1/shop/products/{product['slug']}").json()["product"]
    assert all("id" not in image for image in detail["images"])
    assert all(set(variant) & {"id"} for variant in detail["variants"])


def test_expected_public_routes_remain_usable(client):
    bootstrap = client.get("/api/v1/shop/bootstrap")
    products = client.get("/api/v1/shop/products", params={"sort": "novedades"})
    assert all(response.status_code == 200 for response in (bootstrap, products))
    slug = products.json()["items"][0]["slug"]
    assert client.get(f"/api/v1/shop/products/{slug}").status_code == 200

    from conftest import reservation_payload

    payload = reservation_payload(client)
    availability = client.post("/api/v1/shop/availability", json={"items": payload["items"]})
    assert availability.status_code == 200


def test_public_reservation_rejects_server_owned_fields(client):
    from conftest import reservation_payload

    payload = reservation_payload(client)
    payload.update(
        {
            "status": "entregada",
            "price": 0,
            "total_amount": 0,
            "private_token": "chosen-by-client",
            "internal_notes": "override",
            "folio": "FAKE",
        }
    )
    response = client.post("/api/v1/shop/reservations", json=payload)
    assert response.status_code == 422


def test_public_reservation_limits_reject_before_inventory_changes(client):
    from conftest import reservation_payload

    payload = reservation_payload(client)
    variant_id = payload["items"][0]["variant_id"]
    with db_connection() as db:
        before = db.execute(
            "SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)
        ).fetchone()[0]
        reservation_count = db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]

    payload["items"] = [{"variant_id": variant_id, "quantity": 21}]
    invalid_quantity = client.post("/api/v1/shop/reservations", json=payload)
    assert invalid_quantity.status_code == 422

    oversized = client.post(
        "/api/v1/shop/reservations",
        content=b"x" * (MAX_RESERVATION_BODY_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413

    with db_connection() as db:
        after = db.execute(
            "SELECT reserved_stock FROM product_variants WHERE id=?", (variant_id,)
        ).fetchone()[0]
        after_count = db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
    assert after == before
    assert after_count == reservation_count


def test_public_reservation_rejects_duplicate_lines_and_excess_total_units(client):
    from conftest import reservation_payload

    payload = reservation_payload(client)
    line = payload["items"][0]
    payload["items"] = [line, line]
    assert client.post("/api/v1/shop/reservations", json=payload).status_code == 422

    payload["items"] = [
        {"variant_id": index + 1, "quantity": 20}
        for index in range((MAX_RESERVATION_TOTAL_UNITS // 20) + 1)
    ]
    with pytest.raises(ValidationError):
        ReservationPublicCreate.model_validate(payload)


def test_cors_exposes_download_metadata_headers(client):
    response = client.get("/health", headers={"Origin": "http://testserver"})
    exposed = {
        value.strip().lower()
        for value in response.headers["Access-Control-Expose-Headers"].split(",")
    }
    assert exposed == {"content-disposition", "x-exported-rows"}


def test_admin_cookies_remain_host_only_with_separate_http_only_policy(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    set_cookies = response.headers.get_list("set-cookie")
    session = next(value for value in set_cookies if value.startswith("nebula_admin_session="))
    csrf = next(value for value in set_cookies if value.startswith("nebula_csrf="))
    assert "HttpOnly" in session
    assert "HttpOnly" not in csrf
    assert "SameSite=lax" in session and "SameSite=lax" in csrf
    assert "Domain=" not in session and "Domain=" not in csrf

    production = Settings(
        environment="production",
        public_site_url="https://staging.example.com",
        allowed_origins="https://staging.example.com",
        database_url="postgres://user:password@db.example/nebula?sslmode=require",
        auth_secret="a-unique-production-secret-with-more-than-32-characters",
        auto_migrate=False,
        load_seed_data=False,
    )
    assert production.cookie_secure is True


def _production_settings(**overrides):
    values = {
        "environment": "production",
        "public_site_url": "https://staging.example.com",
        "allowed_origins": "https://staging.example.com",
        "database_url": "postgresql://user:password@db.example/nebula?sslmode=require",
        "auth_secret": "a-unique-production-secret-with-more-than-32-characters",
        "auto_migrate": False,
        "load_seed_data": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_requires_one_exact_canonical_same_origin():
    production = _production_settings(
        migration_database_url="postgresql://user:password@direct.example/nebula",
        migration_database_pool_mode="direct",
    )

    assert production.cors_origins == ("https://staging.example.com",)
    assert production.public_site_url == production.cors_origins[0]


@pytest.mark.parametrize(
    ("public_site_url", "allowed_origins"),
    [
        ("https://staging.example.com", "https://staging.example.com,https://api.example.com"),
        ("https://staging.example.com", "https://api.example.com"),
        ("https://staging.example.com/admin", "https://staging.example.com"),
        ("https://staging.example.com", "https://staging.example.com/api"),
        ("https://staging.example.com?preview=1", "https://staging.example.com?preview=1"),
        ("https://staging.example.com#fragment", "https://staging.example.com#fragment"),
        ("https://user:password@staging.example.com", "https://user:password@staging.example.com"),
        ("https://localhost", "https://localhost"),
        ("https://sub.localhost", "https://sub.localhost"),
        ("https://127.0.0.1", "https://127.0.0.1"),
        ("https://10.0.0.1", "https://10.0.0.1"),
        ("https://8.8.8.8", "https://8.8.8.8"),
        ("http://staging.example.com", "http://staging.example.com"),
        ("https://staging.example.com:443", "https://staging.example.com:443"),
        ("https://staging.example.com/", "https://staging.example.com/"),
        (" https://staging.example.com", " https://staging.example.com"),
    ],
)
def test_production_rejects_non_same_origin_or_noncanonical_urls(
    public_site_url, allowed_origins
):
    with pytest.raises(ValidationError):
        _production_settings(
            public_site_url=public_site_url,
            allowed_origins=allowed_origins,
        )


def test_development_keeps_multiple_local_origins_flexible():
    development = Settings(
        environment="dev",
        public_site_url="http://localhost:3000/app",
        allowed_origins="http://localhost:3000,http://127.0.0.1:3000",
    )

    assert len(development.cors_origins) == 2


def test_invalid_confirmation_token_is_indistinguishable_not_found(client):
    short = client.post("/api/v1/shop/confirmation", json={"token": "short"})
    random = client.post("/api/v1/shop/confirmation", json={"token": "A" * 43})
    assert short.status_code == random.status_code == 404
    assert short.json() == random.json()
    assert short.headers["Cache-Control"] == "no-store"
    assert short.headers["Referrer-Policy"] == "no-referrer"


def test_raw_confirmation_token_is_returned_once_but_only_hash_is_stored(client, caplog):
    response = client.post("/api/v1/shop/reservations", json=reservation_payload(client))
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    created = response.json()
    raw_token = created["private_token"]
    assert len(raw_token) >= 40
    with db_connection() as db:
        row = db.execute(
            "SELECT private_token_hash FROM reservations WHERE folio=?", (created["folio"],)
        ).fetchone()
    assert row["private_token_hash"] == private_token_hash(raw_token)
    assert row["private_token_hash"] != raw_token

    confirmation = client.post("/api/v1/shop/confirmation", json={"token": raw_token})
    assert confirmation.status_code == 200
    assert not confirmation.request.url.query
    assert raw_token not in str(confirmation.request.url)
    assert confirmation.headers["Cache-Control"] == "no-store"
    assert confirmation.headers["Referrer-Policy"] == "no-referrer"
    body = confirmation.json()
    assert not (SENSITIVE_CONFIRMATION_FIELDS & body["reservation"].keys())
    assert all(not (SENSITIVE_CONFIRMATION_FIELDS & item.keys()) for item in body["reservation"]["items"])
    assert "alert_recipients" not in confirmation.text
    assert "recipient_email" not in created
    assert raw_token not in caplog.text
    assert "012180001234567895" not in caplog.text
    assert "test-only-secret-that-is-longer-than-thirty-two-characters" not in caplog.text


def test_login_errors_do_not_enumerate_accounts(client):
    existing = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": "incorrect-password"},
        headers={"Origin": "http://testserver"},
    )
    missing = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "incorrect-password"},
        headers={"Origin": "http://testserver"},
    )
    assert existing.status_code == missing.status_code == 401
    assert existing.json() == missing.json() == {"detail": GENERIC_LOGIN_ERROR}


def test_login_payload_secrets_are_not_logged(client, caplog):
    password = "unique-wrong-password-never-log-this"
    response = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": password},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 401
    assert password not in caplog.text


def test_login_rate_limit(client):
    login_limiter.reset_for_tests()
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": "incorrect-password"},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 401
    limited = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": "incorrect-password"},
        headers={"Origin": "http://testserver"},
    )
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


def test_password_change_checks_current_and_signs_out_other_devices(client):
    login(client)
    other_device = dict(client.cookies)
    client.cookies.clear()
    csrf = login(client)
    new_password = "otra-clave-muy-larga-2026"
    change = lambda current, new: client.post(
        "/api/v1/auth/password",
        json={"current_password": current, "new_password": new},
        headers={"X-CSRF-Token": csrf},
    )

    try:
        assert change("incorrecta", new_password).status_code == 400
        assert change(ADMIN_PASSWORD, "corta").status_code == 422
        assert client.post("/api/v1/auth/password", json={"current_password": ADMIN_PASSWORD, "new_password": new_password}).status_code == 403
        before_change = dict(client.cookies)
        assert change(ADMIN_PASSWORD, new_password).status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 200  # este dispositivo sigue dentro, con sesión nueva

        assert client.cookies[settings.session_cookie_name] != before_change[settings.session_cookie_name]
        for stale in (other_device, before_change):
            client.cookies.clear()
            client.cookies.update(stale)
            assert client.get("/api/v1/auth/me").status_code == 401
    finally:
        # Aunque algo falle, la cuenta compartida vuelve a la contraseña que esperan los demás tests.
        with db_connection() as db:
            db.execute(
                "UPDATE admin_accounts SET password_hash = ? WHERE normalized_email = ?",
                (hash_password(ADMIN_PASSWORD), ADMIN_EMAIL),
            )


def test_login_rate_limit_keys_on_the_visitor_not_the_cdn(client):
    login_limiter.reset_for_tests()
    attempt = lambda forwarded: client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": "incorrect-password"},
        headers={"Origin": "http://testserver", "X-Forwarded-For": forwarded},
    ).status_code
    # Como lo entrega Railway: la visita a la izquierda y luego la CDN (cambia entre peticiones).
    statuses = [attempt(f"8.8.8.8, 152.233.23.{i}") for i in range(6)]
    assert statuses == [401] * 5 + [429]
    # Otra visita que pasa por la misma CDN no hereda el bloqueo.
    assert attempt("9.9.9.9, 152.233.23.1") == 401


def test_rate_limiter_forgets_ips_once_their_window_passes():
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60)
    limiter.check("visita")
    assert limiter._attempts == {}
    limiter.fail("apartado")
    assert "apartado" in limiter._attempts
    later = limiter._attempts["apartado"][0] + 61
    limiter._trim("apartado", later)
    assert limiter._attempts == {}


def test_admin_cookie_and_csrf_are_required_for_mutation(client):
    csrf = login(client)
    assert client.cookies.get("nebula_admin_session")
    without_header = client.post("/api/v1/crm/reservations/1/read")
    assert without_header.status_code == 403
    with_header = client.post("/api/v1/crm/reservations/1/read", headers={"X-CSRF-Token": csrf})
    assert with_header.status_code in {200, 404}


def test_admin_responses_never_return_password_hashes(client):
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        headers={"Origin": "http://testserver"},
    )
    assert login_response.status_code == 200
    assert "csrf" not in login_response.text.lower()
    response = client.get("/api/v1/crm/session")
    assert response.status_code == 200
    assert "password" not in response.text.lower()
    assert "hash" not in response.text.lower()


def test_public_reservations_are_rate_limited_per_ip(client):
    for _ in range(5):
        create_reservation(client)
    with db_connection() as db:
        count = db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]

    blocked = client.post("/api/v1/shop/reservations", json=reservation_payload(client))
    assert blocked.status_code == 429
    with db_connection() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == count


def test_delivery_date_must_be_written_as_year_month_day(client):
    from datetime import date

    payload = reservation_payload(client)
    year, week, weekday = date.fromisoformat(payload["delivery_date"]).isocalendar()
    payload["delivery_date"] = f"{year}-W{week:02d}-{weekday}"  # misma fecha, otro formato ISO
    response = client.post("/api/v1/shop/reservations", json=payload)
    assert response.status_code == 400
    assert "fecha" in response.json()["detail"]


def test_long_customer_note_is_rejected_instead_of_silently_cut(client):
    payload = reservation_payload(client)
    payload["notes"] = "x" * 401
    assert client.post("/api/v1/shop/reservations", json=payload).status_code == 422
    payload["notes"] = "Casa azul, portón negro. " * 16  # 400 caracteres
    created = client.post("/api/v1/shop/reservations", json=payload)
    assert created.status_code == 200, created.text
