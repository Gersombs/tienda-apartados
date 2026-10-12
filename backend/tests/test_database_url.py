from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

import core.database_url as database_url_module
from core.database_url import (
    create_configured_async_engine,
    database_engine_configuration,
    normalize_database_url,
)


@pytest.mark.parametrize(
    ("raw_url", "expected_ssl"),
    [
        ("postgres://user:password@db.example/nebula", None),
        ("postgresql://user:password@db.example/nebula?sslmode=require", "require"),
        ("postgresql+asyncpg://user:password@db.example/nebula?sslmode=verify-ca", "verify-ca"),
        ("postgresql://user:password@db.example/nebula?sslmode=verify-full", "verify-full"),
    ],
)
def test_postgres_urls_use_asyncpg_and_preserve_tls_intent(raw_url, expected_ssl):
    target = normalize_database_url(raw_url)

    parsed = make_url(target.url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert "sslmode" not in parsed.query
    assert target.connect_args == ({"ssl": expected_ssl} if expected_ssl else {})


def test_provider_only_parameters_are_removed_without_losing_other_options():
    target = normalize_database_url(
        "postgresql://user:password@db.example/nebula"
        "?sslmode=require&channel_binding=require&prepared_statement_cache_size=0"
    )

    parsed = make_url(target.url)
    assert parsed.query == {"prepared_statement_cache_size": "0"}
    assert target.connect_args == {"ssl": "require"}


@pytest.mark.parametrize(
    ("raw_url", "expected_prefix"),
    [
        ("sqlite:///./local.db", "sqlite+aiosqlite:///"),
        ("sqlite+aiosqlite:///./local.db", "sqlite+aiosqlite:///"),
    ],
)
def test_sqlite_urls_remain_async_and_need_no_connect_args(raw_url, expected_prefix):
    target = normalize_database_url(raw_url)

    assert target.url.startswith(expected_prefix)
    assert target.connect_args == {}


@pytest.mark.parametrize(
    "raw_url",
    [
        "mysql://user:password@db.example/nebula",
        "postgresql://user:password@db.example/nebula?sslmode=unknown",
        "not a database url",
    ],
)
def test_unsupported_urls_fail_without_echoing_the_url(raw_url):
    with pytest.raises(ValueError) as caught:
        normalize_database_url(raw_url)

    assert raw_url not in str(caught.value)


def test_direct_postgres_keeps_driver_and_sqlalchemy_cache_defaults(monkeypatch):
    captured = {}
    sentinel = object()

    def fake_create(url, **options):
        captured.update(url=url, options=options)
        return sentinel

    monkeypatch.setattr(database_url_module, "create_async_engine", fake_create)
    target = database_engine_configuration(
        "postgresql://user:password@db.example/nebula?sslmode=require",
        pool_mode="direct",
    )
    engine = create_configured_async_engine(target, echo=False)

    assert engine is sentinel
    assert target.transaction_pooler is False
    assert captured["url"].startswith("postgresql+asyncpg://")
    assert captured["options"]["connect_args"] == {"ssl": "require"}
    assert "poolclass" not in captured["options"]
    assert "prepared_statement_cache_size" not in captured["options"]["connect_args"]
    assert "statement_cache_size" not in captured["options"]["connect_args"]


@pytest.mark.parametrize(
    ("url", "pool_mode"),
    [
        ("postgresql://user:password@project.pooler.example.com:6543/nebula", "auto"),
        ("postgresql://user:password@db.example.com/nebula", "transaction"),
    ],
)
def test_transaction_pooler_disables_both_caches_and_uses_nullpool(
    monkeypatch, url, pool_mode
):
    captured = {}

    def fake_create(engine_url, **options):
        captured.update(url=engine_url, options=options)
        return object()

    monkeypatch.setattr(database_url_module, "create_async_engine", fake_create)
    target = database_engine_configuration(url, pool_mode=pool_mode)
    create_configured_async_engine(
        target,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

    args = captured["options"]["connect_args"]
    assert target.transaction_pooler is True
    assert captured["options"]["poolclass"] is NullPool
    assert "pool_size" not in captured["options"]
    assert "max_overflow" not in captured["options"]
    assert "pool_pre_ping" not in captured["options"]
    assert args["prepared_statement_cache_size"] == 0
    assert args["statement_cache_size"] == 0
    assert callable(args["prepared_statement_name_func"])
    assert args["prepared_statement_name_func"]() != args["prepared_statement_name_func"]()


def test_auto_pooler_detection_uses_only_endpoint_not_credentials():
    target = database_engine_configuration(
        "postgresql://pooler-user:pgbouncer-password@db.example.com:5432/nebula",
        pool_mode="auto",
    )

    assert target.transaction_pooler is False
