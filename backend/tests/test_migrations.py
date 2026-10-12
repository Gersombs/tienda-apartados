from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
HEAD_REVISION = "20260825_02"


def _env(database: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "ENVIRONMENT": "test",
            "DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}",
            "APP_DEBUG": "false",
            "AUTO_MIGRATE": "false",
            "LOAD_SEED_DATA": "false",
        }
    )
    env.pop("ALLOW_LEGACY_TOKEN_INVALIDATION", None)
    return env


def _alembic(config: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(config), *args],
        cwd=BACKEND_DIR,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_direct_alembic_upgrade_creates_a_fresh_database(tmp_path):
    database = tmp_path / "fresh.db"
    result = _alembic(ALEMBIC_INI, _env(database), "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD_REVISION
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"reservations", "admin_accounts", "inventory_movements", "product_images"} <= tables
    checked = _alembic(ALEMBIC_INI, _env(database), "check")
    assert checked.returncode == 0, checked.stderr
    assert "No new upgrade operations detected" in checked.stdout


def test_migration_database_url_takes_priority_over_runtime_database_url(tmp_path):
    runtime_database = tmp_path / "runtime-must-stay-unused.db"
    migration_database = tmp_path / "direct-migration.db"
    env = _env(runtime_database)
    env["MIGRATION_DATABASE_URL"] = (
        f"sqlite+aiosqlite:///{migration_database.as_posix()}"
    )

    result = _alembic(ALEMBIC_INI, env, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    assert migration_database.exists()
    assert not runtime_database.exists()
    with sqlite3.connect(migration_database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD_REVISION


@pytest.mark.parametrize("configured", ["", '""', "''", "   "])
def test_alembic_treats_empty_and_quoted_empty_urls_as_absent(tmp_path, configured):
    database = tmp_path / f"quoted-{len(configured)}-{ord(configured[:1] or 'x')}.db"
    config = tmp_path / f"alembic-{len(configured)}-{ord(configured[:1] or 'x')}.ini"
    content = ALEMBIC_INI.read_text(encoding="utf-8")
    content = content.replace("script_location = %(here)s/alembic", f"script_location = {BACKEND_DIR.as_posix()}/alembic")
    content = content.replace("sqlalchemy.url =", f"sqlalchemy.url = {configured}")
    config.write_text(content, encoding="utf-8")
    result = _alembic(config, _env(database), "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD_REVISION


def test_legacy_schema_requires_opt_in_then_preserves_and_revokes_data(tmp_path):
    database = tmp_path / "legacy.db"
    env = _env(database)
    baseline = _alembic(ALEMBIC_INI, env, "upgrade", "3e67152dc4ff")
    assert baseline.returncode == 0, baseline.stderr

    raw_token = "legacy-private-token-that-must-never-survive"
    legacy_origin = "https://" + "m" + "gx-backend-" + "c" + "dn." + "meta" + "dl.com"
    legacy_logo = legacy_origin + "/generate/images/1003084/2026-08-24/vdlwpoycakgq/logo-nebula-beauty-mx.png"
    with sqlite3.connect(database) as db:
        db.execute(
            """
            INSERT INTO reservations
                (folio, private_token, token_revoked, status, total_amount, item_count,
                 is_unread, privacy_accepted, stock_released)
            VALUES ('AP-LEGACY-1', ?, 0, 'recibida', 125, 1, 1, 1, 0)
            """,
            (raw_token,),
        )
        db.execute("INSERT INTO store_settings (shop_name, logo_url) VALUES ('Nébula', ?)", (legacy_logo,))
        db.commit()

    refused = _alembic(ALEMBIC_INI, env, "upgrade", "head")
    assert refused.returncode != 0
    assert "ALLOW_LEGACY_TOKEN_INVALIDATION" in refused.stderr
    with sqlite3.connect(database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(reservations)")}
        assert "private_token" in columns
        assert db.execute("SELECT COUNT(*) FROM reservations WHERE folio='AP-LEGACY-1'").fetchone()[0] == 1

    env["ALLOW_LEGACY_TOKEN_INVALIDATION"] = "1"
    migrated = _alembic(ALEMBIC_INI, env, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    with sqlite3.connect(database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(reservations)")}
        row = db.execute(
            "SELECT folio, private_token_hash, token_revoked, total_amount FROM reservations WHERE folio='AP-LEGACY-1'"
        ).fetchone()
        logo = db.execute("SELECT logo_url FROM store_settings").fetchone()[0]
        revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert "private_token" not in columns
    assert row[0] == "AP-LEGACY-1"
    assert len(row[1]) == 64 and raw_token not in row[1]
    assert row[2] == 1 and row[3] == 125
    assert logo == "/images/logo-nebula-beauty-mx.webp"
    assert revision == HEAD_REVISION
