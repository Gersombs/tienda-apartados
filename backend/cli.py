"""Local maintenance commands. Run from the backend directory."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib
import json
import pkgutil
import re
import sys
import uuid
from datetime import timedelta

from sqlalchemy import String, delete, func, make_url, select
from sqlalchemy.ext.asyncio import AsyncSession

import models

from core.auth import hash_password, validate_admin_email
from core.config import settings
from core.database_url import normalize_database_url
from core.database import Base, db_manager
from core.time_utils import utc_now
from models.admin_accounts import Admin_accounts
from models.admin_sessions import Admin_sessions
from models.store_settings import Store_settings
from models.uploaded_images import Uploaded_images
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


PUBLIC_TEXT_FIELDS = ("how_it_works", "faq_content", "reservation_policy", "delivery_instructions", "privacy_policy")


def template_settings(name: str) -> dict:
    """Configuración de demostración con el nombre de la tienda en lugar del de ejemplo."""
    template = json.loads((MOCK_DATA_DIR / "store_settings.json").read_text(encoding="utf-8"))[0]
    return {key: value.replace(DEMO_SHOP_NAME, name) if isinstance(value, str) else value for key, value in template.items()}


async def restore_texts(apply: bool) -> None:
    """Vuelve a poner los textos base (con saltos de línea y el flujo actual) en una tienda existente."""
    await initialize_database()
    try:
        async with db_manager.async_session_maker() as db:
            store = (await db.execute(select(Store_settings).order_by(Store_settings.id).limit(1))).scalars().first()
            if store is None:
                print("Esta base no tiene tienda configurada.")
                return
            base = template_settings(store.shop_name)
            changed = [field for field in PUBLIC_TEXT_FIELDS if (getattr(store, field) or "") != base[field]]
            if not changed:
                print("Los textos ya están al día.")
                return
            print("Textos que se reemplazarán (se pierden los cambios hechos a mano en ellos):")
            for field in changed:
                print(f"  - {field}")
            if not apply:
                print("No se cambió nada. Agrega --aplicar para reemplazarlos.")
                return
            for field in changed:
                setattr(store, field, base[field])
            await db.commit()
            print("Listo.")
    finally:
        await close_database()


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
            fields = template_settings(name)
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


IMAGE_URL = re.compile(r"/api/v1/shop/images/(\d+)")


async def unused_image_ids(db: AsyncSession, min_age: timedelta = timedelta(days=1)) -> list[int]:
    """Fotos subidas que ningún texto de la base menciona (productos, categorías,
    portada, logo y también apartados viejos, que guardan su propia copia de la URL).

    Las de menos de `min_age` se respetan: pueden estar a medio guardar en el panel.
    """
    for module in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"models.{module.name}")
    used: set[int] = set()
    for table in Base.metadata.sorted_tables:
        columns = [c for c in table.columns if isinstance(c.type, String)]
        if table.name == Uploaded_images.__tablename__ or not columns:
            continue
        for row in await db.execute(select(*columns)):
            for value in row:
                used.update(int(found) for found in IMAGE_URL.findall(value or ""))
    candidates = await db.execute(
        select(Uploaded_images.id).where(Uploaded_images.created_at < utc_now() - min_age)
    )
    return [image_id for image_id in candidates.scalars() if image_id not in used]


async def clean_images(delete_them: bool) -> None:
    await initialize_database()
    try:
        async with db_manager.async_session_maker() as db:
            ids = await unused_image_ids(db)
            size = (
                await db.execute(select(func.coalesce(func.sum(Uploaded_images.size_bytes), 0)).where(Uploaded_images.id.in_(ids)))
            ).scalar_one() if ids else 0
            print(f"Fotos sin usar: {len(ids)} ({size / 1_000_000:.1f} MB).")
            if ids and delete_them:
                await db.execute(delete(Uploaded_images).where(Uploaded_images.id.in_(ids)))
                await db.commit()
                print("Borradas.")
            elif ids:
                print("No se borró nada. Agrega --borrar para eliminarlas.")
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
    images = subparsers.add_parser(
        "limpiar-fotos",
        help="Mostrar (o borrar con --borrar) las fotos subidas que ya nada usa",
    )
    images.add_argument("--borrar", action="store_true", help="Borrarlas de verdad")
    texts = subparsers.add_parser(
        "restaurar-textos",
        help="Mostrar (o reemplazar con --aplicar) los textos públicos por los textos base actuales",
    )
    texts.add_argument("--aplicar", action="store_true", help="Reemplazarlos de verdad")
    args = parser.parse_args()

    if args.command in {"create-admin", "nueva-tienda", "limpiar-fotos", "restaurar-textos"}:
        # Muestra el destino antes de pedir la contraseña: evita crear la tienda en la base equivocada.
        target = make_url(normalize_database_url(settings.database_url).url)
        print(f"Base de datos: {target.render_as_string(hide_password=True)}")
    if args.command in {"create-admin", "nueva-tienda"}:
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
    if args.command == "restaurar-textos":
        asyncio.run(restore_texts(args.aplicar))
        return 0
    if args.command == "limpiar-fotos":
        asyncio.run(clean_images(args.borrar))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
