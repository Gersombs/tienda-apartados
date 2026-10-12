"""API pública de la tienda Nébula Beauty MX.

Estos endpoints no requieren autenticación porque las clientas no crean cuenta.
Nunca exponen datos bancarios ni configuración privada: los datos bancarios solo
se devuelven en `/confirmacion` cuando se presenta un token privado válido.
"""

import logging
from typing import Annotated, Any, Dict, List, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.config import settings as app_settings
from models.categories import Categories
from models.products import Products
from models.uploaded_images import Uploaded_images
from routers.auth import LoginRateLimiter, _rate_keys
from schemas.shop import (
    AvailabilityRequest,
    AvailabilityPublicResponse,
    BootstrapPublicResponse,
    ContentPublicResponse,
    ConfirmationTokenRequest,
    DeliveryOptionsPublicResponse,
    ProductDetailResponse,
    ProductsPublicResponse,
    PublicConfirmationResponse,
    ReservationCreatedPublic,
    ReservationPublicCreate,
)
from services import mailer
from services.reservation_engine import (
    ACTIVE_STATUSES,
    STATUS_LABELS,
    InvalidReservationExpiration,
    ReservationError,
    cancel_by_customer,
    check_cart_availability,
    create_reservation,
    expire_due_reservations,
    get_confirmation_reservation,
    get_private_settings,
    load_delivery_options,
    load_images_for_products,
    load_reservation_items,
    load_variants_for_products,
    serialize_product,
    store_settings_public,
    get_store_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/shop", tags=["shop"])
# shortcut: límite en memoria por IP (1 réplica); con varias réplicas, moverlo al proxy o a la BD.
reservation_limiter = LoginRateLimiter(max_attempts=5, window_seconds=600)


async def _categories_map(db: AsyncSession) -> Dict[int, Categories]:
    result = await db.execute(select(Categories).order_by(Categories.sort_order, Categories.id))
    return {c.id: c for c in result.scalars().all() if c.is_active is not False}


@router.get("/bootstrap", response_model=BootstrapPublicResponse)
async def bootstrap(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Configuración pública, categorías, puntos de entrega y productos destacados."""
    try:
        # Barrido perezoso de vencimientos para que la disponibilidad pública sea real.
        await expire_due_reservations(db)

        settings = await get_store_settings(db)
        config = store_settings_public(settings)
        categories = await _categories_map(db)

        featured_result = await db.execute(
            select(Products)
            .where(Products.is_featured.is_(True), Products.is_active.is_(True))
            .order_by(Products.sort_order, Products.id)
            .limit(8)
        )
        featured = list(featured_result.scalars().all())
        featured = [p for p in featured if not p.is_archived]
        ids = [p.id for p in featured]
        images = await load_images_for_products(db, ids)
        variants = await load_variants_for_products(db, ids)

        delivery_points = await load_delivery_options(db, config["reservation_window_days"])
        return {
            "settings": config,
            "categories": [
                {
                    "name": c.name,
                    "slug": c.slug,
                    "description": c.description or "",
                    "image_url": c.image_url or "",
                }
                for c in categories.values()
            ],
            "featured": [
                serialize_product(
                    p,
                    images.get(p.id, []),
                    variants.get(p.id, []),
                    category_name=categories[p.category_id].name if p.category_id in categories else "",
                    category_slug=categories[p.category_id].slug if p.category_id in categories else "",
                )
                for p in featured
            ],
            "delivery_points": delivery_points,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en bootstrap de la tienda: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos cargar la tienda. Intenta de nuevo.")


@router.get("/products", response_model=ProductsPublicResponse)
async def list_products(
    search: Annotated[str, Query(max_length=120)] = "",
    category: Annotated[str, Query(max_length=120, pattern=r"^[a-z0-9-]*$")] = "",
    sort: Literal["destacados", "precio_asc", "precio_desc", "novedades"] = "destacados",
    availability: Literal["todos", "disponibles", "ultimas"] = "todos",
    min_price: Annotated[float, Query(ge=0, le=1_000_000, allow_inf_nan=False)] = 0,
    max_price: Annotated[float, Query(ge=0, le=1_000_000, allow_inf_nan=False)] = 0,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Catálogo con búsqueda, filtros y orden."""
    try:
        categories = await _categories_map(db)
        result = await db.execute(
            select(Products)
            .where(Products.is_active.is_(True))
            .order_by(Products.sort_order, Products.id)
        )
        products = [p for p in result.scalars().all() if not p.is_archived]

        if category:
            match = next((c for c in categories.values() if c.slug == category), None)
            if match is None:
                return {"items": [], "total": 0, "category": None}
            products = [p for p in products if p.category_id == match.id]

        needle = (search or "").strip().lower()
        if needle:
            products = [
                p
                for p in products
                if needle in (p.name or "").lower()
                or needle in (p.short_description or "").lower()
                or needle in (p.tags or "").lower()
                or needle in (p.full_description or "").lower()
            ]

        if min_price and min_price > 0:
            products = [p for p in products if float(p.price or 0) >= min_price]
        if max_price and max_price > 0:
            products = [p for p in products if float(p.price or 0) <= max_price]

        ids = [p.id for p in products]
        images = await load_images_for_products(db, ids)
        variants = await load_variants_for_products(db, ids)

        payload = [
            serialize_product(
                p,
                images.get(p.id, []),
                variants.get(p.id, []),
                category_name=categories[p.category_id].name if p.category_id in categories else "",
                category_slug=categories[p.category_id].slug if p.category_id in categories else "",
            )
            for p in products
        ]

        if availability == "disponibles":
            payload = [item for item in payload if item["available_units"] > 0]
        elif availability == "ultimas":
            payload = [item for item in payload if 0 < item["available_units"] <= 3]

        if sort == "precio_asc":
            payload.sort(key=lambda i: i["price"])
        elif sort == "precio_desc":
            payload.sort(key=lambda i: i["price"], reverse=True)
        elif sort == "novedades":
            created_at = {product.slug: str(product.created_at or "") for product in products}
            payload.sort(key=lambda item: created_at.get(item["slug"], ""), reverse=True)
        else:
            payload.sort(key=lambda i: (not i["is_featured"], i["available_units"] == 0))

        category_payload = None
        if category:
            match = next((c for c in categories.values() if c.slug == category), None)
            if match is not None:
                category_payload = {
                    "name": match.name,
                    "slug": match.slug,
                    "description": match.description or "",
                    "image_url": match.image_url or "",
                }

        return {"items": payload, "total": len(payload), "category": category_payload}
    except Exception as exc:  # noqa: BLE001
        logger.error("Error listando productos: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos cargar el catálogo.")


@router.get("/products/{slug}", response_model=ProductDetailResponse)
async def product_detail(
    slug: Annotated[str, Path(min_length=1, max_length=120, pattern=r"^[a-z0-9-]+$")],
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Ficha individual del producto. Los agotados conservan su URL."""
    try:
        result = await db.execute(select(Products).where(Products.slug == slug))
        product = result.scalars().first()
        if product is None or product.is_active is False or product.is_archived:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        categories = await _categories_map(db)
        images = await load_images_for_products(db, [product.id])
        variants = await load_variants_for_products(db, [product.id])
        detail = serialize_product(
            product,
            images.get(product.id, []),
            variants.get(product.id, []),
            category_name=categories[product.category_id].name if product.category_id in categories else "",
            category_slug=categories[product.category_id].slug if product.category_id in categories else "",
            include_detail=True,
        )

        related_result = await db.execute(
            select(Products)
            .where(
                Products.category_id == product.category_id,
                Products.id != product.id,
                Products.is_active.is_(True),
            )
            .order_by(Products.sort_order, Products.id)
            .limit(4)
        )
        related = [p for p in related_result.scalars().all() if not p.is_archived]
        related_ids = [p.id for p in related]
        related_images = await load_images_for_products(db, related_ids)
        related_variants = await load_variants_for_products(db, related_ids)

        return {
            "product": detail,
            "related": [
                serialize_product(
                    p,
                    related_images.get(p.id, []),
                    related_variants.get(p.id, []),
                    category_name=categories[p.category_id].name if p.category_id in categories else "",
                    category_slug=categories[p.category_id].slug if p.category_id in categories else "",
                )
                for p in related
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en ficha de producto %s: %s", slug, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos cargar el producto.")


@router.get("/delivery-options", response_model=DeliveryOptionsPublicResponse)
async def delivery_options(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Puntos de entrega con fechas y horarios realmente disponibles."""
    try:
        settings = await get_store_settings(db)
        config = store_settings_public(settings)
        points = await load_delivery_options(db, config["reservation_window_days"])
        return {
            "delivery_points": points,
            "reservation_window_days": config["reservation_window_days"],
            "grace_period_hours": config["grace_period_hours"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Error cargando puntos de entrega: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos cargar los puntos de entrega.")


@router.post("/availability", response_model=AvailabilityPublicResponse, response_model_exclude_none=True)
async def availability(
    data: AvailabilityRequest, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Revalida precio y disponibilidad del apartado guardado en el navegador."""
    try:
        return await check_cart_availability(
            db, [{"variant_id": i.variant_id, "quantity": i.quantity} for i in data.items]
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error revalidando el apartado: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos revisar tu apartado.")


@router.post("/reservations", response_model=ReservationCreatedPublic)
async def submit_reservation(
    data: ReservationPublicCreate, request: Request, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Crea la solicitud de apartado y envía los correos correspondientes.

    La confirmación siempre se devuelve, incluso si el correo falla: el error
    queda registrado en la bitácora para reenviarse desde el CRM.
    """
    ip_key = _rate_keys(request, data.email)[0]
    reservation_limiter.check(ip_key)
    try:
        created = await create_reservation(
            db,
            {
                "full_name": data.full_name,
                "whatsapp": data.whatsapp,
                "email": data.email,
                "delivery_point_id": data.delivery_point_id,
                "delivery_date": data.delivery_date,
                "slot_start": data.slot_start,
                "notes": data.notes,
                "privacy_accepted": data.privacy_accepted,
                "items": [{"variant_id": i.variant_id, "quantity": i.quantity} for i in data.items],
            },
        )
    except ReservationError as exc:
        raise HTTPException(status_code=409 if exc.code == "duplicate" else 400, detail=exc.message)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error("Error creando la reservación: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos registrar tu apartado. Intenta de nuevo.")

    reservation_limiter.fail(ip_key)  # cuenta sólo los apartados creados
    try:
        await mailer.dispatch_reservation_emails(
            db,
            created["id"],
            [mailer.TEMPLATE_RECEIVED, mailer.TEMPLATE_BUSINESS_ALERT],
            app_host=app_settings.public_site_url,
            confirmation_token=created["private_token"],
        )
    except Exception as exc:  # noqa: BLE001
        # El apartado nunca se elimina por un fallo de correo.
        logger.error("Fallo al enviar correos del folio %s: %s", created["folio"], exc, exc_info=True)

    return {
        "folio": created["folio"],
        "private_token": created["private_token"],
        "total_amount": created["total_amount"],
        "message": "Recibimos tu solicitud de apartado.",
    }


def _public_confirmation(reservation: Any, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Allowlist the minimum fields needed to render a private confirmation."""
    return {
        "folio": reservation.folio,
        "status": reservation.status,
        "status_label": STATUS_LABELS.get(reservation.status, reservation.status),
        "delivery_point_name": reservation.delivery_point_name or "",
        "delivery_point_reference": reservation.delivery_point_reference or "",
        "delivery_date": reservation.delivery_date or "",
        "slot_start": reservation.slot_start or "",
        "slot_end": reservation.slot_end or "",
        "total_amount": round(float(reservation.total_amount or 0), 2),
        "item_count": int(reservation.item_count or 0),
        "expires_at": reservation.expires_at or "",
        "cancel_reason": reservation.cancel_reason or "",
        "items": [
            {
                "product_name": item["product_name"],
                "variant_label": item["variant_label"],
                "unit_price": item["unit_price"],
                "quantity": item["quantity"],
                "line_total": item["line_total"],
                "image_url": item["image_url"],
            }
            for item in items
        ],
    }


@router.post("/confirmation", response_model=PublicConfirmationResponse)
async def confirmation(data: ConfirmationTokenRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Confirmación privada. Solo con el token válido se revelan los datos bancarios."""
    try:
        reservation = await get_confirmation_reservation(db, data.token)
        if reservation is None:
            raise HTTPException(status_code=404, detail="No encontramos esta reservación.")
        settings = await get_store_settings(db)
        config = store_settings_public(settings)
        items = await load_reservation_items(db, reservation.id)
        bank_details_allowed = reservation.status in ACTIVE_STATUSES
        private = await get_private_settings(db) if bank_details_allowed else None
        return {
            "reservation": _public_confirmation(reservation, items),
            "settings": {
                "shop_name": config["shop_name"],
                "logo_url": config["logo_url"],
                "contact_whatsapp": config["contact_whatsapp"],
                "delivery_instructions": config["delivery_instructions"],
                "reservation_policy": config["reservation_policy"],
            },
            "bank_details": {
                "bank_name": (private.bank_name if private else "") or "",
                "account_holder": (private.account_holder if private else "") or "",
                "clabe": (private.clabe if private else "") or "",
                "account_number": (private.account_number if private else "") or "",
                "transfer_instructions": (private.transfer_instructions if private else "") or "",
            },
        }
    except HTTPException:
        raise
    except InvalidReservationExpiration as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error("Error cargando la confirmación: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos cargar tu confirmación.")


@router.post("/confirmation/cancel")
async def cancel_confirmation(data: ConfirmationTokenRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """La clienta cancela con su enlace privado: libera las piezas y la tienda lo ve en el CRM, sin correos."""
    try:
        reservation = await cancel_by_customer(db, data.token)
    except ReservationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error("Error cancelando desde la confirmación: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos cancelar tu apartado. Intenta de nuevo.")
    if reservation is None:
        raise HTTPException(status_code=404, detail="No encontramos esta reservación.")
    return {"status": reservation.status, "status_label": STATUS_LABELS[reservation.status]}


@router.get("/images/{image_id}")
async def uploaded_image(
    image_id: Annotated[int, Path(gt=0)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Fotos subidas desde el CRM. Nunca cambian: cada subida recibe un id nuevo."""
    row = (
        await db.execute(
            select(Uploaded_images.content_type, Uploaded_images.data).where(
                Uploaded_images.id == image_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    return Response(
        content=row.data,
        media_type=row.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/content", response_model=ContentPublicResponse)
async def content(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Textos editables: cómo funciona, preguntas frecuentes, privacidad y políticas."""
    try:
        settings = await get_store_settings(db)
        config = store_settings_public(settings)
        return {
            "shop_name": config["shop_name"],
            "how_it_works": config["how_it_works"],
            "faq_content": config["faq_content"],
            "privacy_policy": config["privacy_policy"],
            "reservation_policy": config["reservation_policy"],
            "delivery_instructions": config["delivery_instructions"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Error cargando el contenido editable: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos cargar el contenido.")
