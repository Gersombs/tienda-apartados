"""Local maintenance commands. Run from the backend directory."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import uuid

from sqlalchemy import delete, select

from core.auth import hash_password, validate_admin_email
from core.database import db_manager
from models.admin_accounts import Admin_accounts
from models.admin_sessions import Admin_sessions
from services.database import close_database, initialize_database
from services.migrations import upgrade_database
from services.mock_data import initialize_production_catalog


async def create_admin(email: str, name: str, password: str) -> None:
    normalized = validate_admin_email(email)
    password_hash = hash_password(password)

    await upgrade_database()
    await initialize_database()
    try:
        async with db_manager.async_session_maker() as db:
            existing = (
                await db.execute(
                    select(Admin_accounts).where(Admin_accounts.normalized_email == normalized).limit(1)
                )
            ).scalars().first()
            if existing is None:
                existing = Admin_accounts(
                    auth_user_id=str(uuid.uuid4()),
                    email=normalized,
                    normalized_email=normalized,
                    password_hash=password_hash,
                    name=(name or "Administradora").strip()[:120],
                    role="owner",
                    is_active=True,
                )
                db.add(existing)
                action = "creada"
            else:
                existing.email = normalized
                existing.normalized_email = normalized
                existing.password_hash = password_hash
                existing.name = (name or existing.name or "Administradora").strip()[:120]
                existing.role = "owner"
                existing.is_active = True
                await db.execute(delete(Admin_sessions).where(Admin_sessions.admin_id == existing.id))
                action = "actualizada"
            await db.commit()
            print(f"Cuenta administrativa {action}: {normalized}")
    finally:
        await close_database()


async def init_catalog() -> None:
    """Apply migrations and atomically create only publishable catalog data."""

    await upgrade_database()
    await initialize_database()
    try:
        inserted = await initialize_production_catalog()
        total = sum(inserted.values())
        if total:
            print(f"Catálogo inicial creado: {total} filas.")
        else:
            print("El catálogo ya estaba inicializado; no se modificó.")
    finally:
        await close_database()


def main() -> int:
    parser = argparse.ArgumentParser(description="Mantenimiento local de Nébula Beauty MX")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-admin", help="Crear o restablecer una cuenta administrativa")
    create.add_argument("--email", required=True)
    create.add_argument("--name", default="Administradora")
    create.add_argument(
        "--password-stdin",
        action="store_true",
        help="Leer una contraseña desde stdin; evita exponerla en el historial del shell",
    )
    subparsers.add_parser(
        "init-catalog",
        help="Aplicar migraciones y crear una sola vez el catálogo publicable",
    )
    args = parser.parse_args()

    if args.command == "create-admin":
        password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass("Contraseña: ")
        confirmation = password if args.password_stdin else getpass.getpass("Confirma la contraseña: ")
        if password != confirmation:
            parser.error("Las contraseñas no coinciden.")
        asyncio.run(create_admin(args.email, args.name, password))
        return 0
    if args.command == "init-catalog":
        asyncio.run(init_catalog())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
