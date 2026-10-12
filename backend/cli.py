"""Local maintenance commands. Run from the backend directory."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import uuid

from sqlalchemy import delete, make_url, select

from core.auth import hash_password, validate_admin_email
from core.config import settings
from core.database_url import normalize_database_url
from core.database import db_manager
from models.admin_accounts import Admin_accounts
from models.admin_sessions import Admin_sessions
from models.store_settings import Store_settings
from services.database import close_database, initialize_database
from services.migrations import upgrade_database
from services.mock_data import MOCK_DATA_DIR, initialize_production_catalog


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


DEMO_SHOP_NAME = "Nébula Beauty MX"


async def new_store(name: str, contact_email: str, whatsapp: str) -> bool:
    """Crea la configuración de una tienda en blanco: sin catálogo ni puntos de entrega.

    Reutiliza los textos de demostración (cómo funciona, preguntas, políticas) con el
    nombre de la tienda, para que la emprendedora edite en vez de escribir desde cero.
    Devuelve False sin tocar nada si la tienda ya estaba configurada.
    """

    await upgrade_database()
    await initialize_database()
    try:
        async with db_manager.async_session_maker() as db:
            if (await db.execute(select(Store_settings.id).limit(1))).first() is not None:
                return False
            template = json.loads((MOCK_DATA_DIR / "store_settings.json").read_text(encoding="utf-8"))[0]
            fields = {
                key: value.replace(DEMO_SHOP_NAME, name) if isinstance(value, str) else value
                for key, value in template.items()
            }
            fields.update(
                shop_name=name,
                tagline="",
                logo_url="",
                hero_image_url="",
                contact_email=contact_email,
                contact_whatsapp=whatsapp,
                instagram_url="",
                tiktok_url="",
                facebook_url="",
            )
            db.add(Store_settings(**fields))
            await db.commit()
            return True
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
    store = subparsers.add_parser(
        "nueva-tienda",
        help="Tienda en blanco: migraciones, textos base con su nombre y su administradora",
    )
    store.add_argument("--nombre", required=True, help="Nombre visible de la tienda")
    store.add_argument("--email", required=True, help="Correo de la administradora (y de contacto)")
    store.add_argument("--admin-nombre", default="Administradora")
    store.add_argument("--whatsapp", default="", help="WhatsApp público a 10 dígitos")
    store.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()

    if args.command in {"create-admin", "nueva-tienda"}:
        # Muestra el destino antes de pedir la contraseña: evita crear la tienda en la base equivocada.
        target = make_url(normalize_database_url(settings.database_url).url)
        print(f"Base de datos: {target.render_as_string(hide_password=True)}")
        password =sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass("Contraseña: ")
        confirmation = password if args.password_stdin else getpass.getpass("Confirma la contraseña: ")
        if password != confirmation:
            parser.error("Las contraseñas no coinciden.")
        try:
            hash_password(password)  # valida longitud antes de tocar la base
        except ValueError as exc:
            parser.error(str(exc))

    if args.command == "create-admin":
        asyncio.run(create_admin(args.email, args.name, password))
        return 0
    if args.command == "nueva-tienda":
        name = args.nombre.strip()[:120]
        if not name:
            parser.error("El nombre de la tienda no puede estar vacío.")
        whatsapp = "".join(ch for ch in args.whatsapp if ch.isdigit())
        if whatsapp and len(whatsapp) != 10:
            parser.error("El WhatsApp debe tener 10 dígitos.")
        contact_email = validate_admin_email(args.email)
        created = asyncio.run(new_store(name, contact_email, whatsapp))
        print("Tienda creada." if created else "La tienda ya estaba configurada; no se modificó.")
        asyncio.run(create_admin(args.email, args.admin_nombre, password))
        return 0
    if args.command == "init-catalog":
        asyncio.run(init_catalog())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
