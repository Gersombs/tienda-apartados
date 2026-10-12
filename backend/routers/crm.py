"""API del CRM administrativo de Nébula Beauty MX.

El router completo recibe las dependencias de sesión administrativa y CSRF al
registrarse en ``main.py``. El primer administrador solo puede crearse mediante
el comando CLI local documentado; no existe registro por HTTP.
"""

import csv
import io
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.auth import new_secret_token, private_token_hash
from core.config import settings as app_settings
from core.csv_security import sanitize_csv_text
from dependencies.auth import get_current_admin_account, get_current_user
from models.admin_accounts import Admin_accounts
from models.categories import Categories
from models.customers import Customers
from models.delivery_points import Delivery_points
from models.delivery_slots import Delivery_slots
from models.inventory_movements import Inventory_movements
from models.private_settings import Private_settings
from models.product_images import Product_images
from models.product_variants import Product_variants
from models.products import Products
from models.reservation_status_history import Reservation_status_history
from models.reservations import Reservations
from models.store_settings import Store_settings
from models.uploaded_images import Uploaded_images
from schemas.auth import UserResponse
from services import mailer
from services.reservation_engine import (
    ACTIVE_STATUSES,
    ALL_STATUSES,
    STATUS_DELIVERED,
    STATUS_EXPIRED,
    STATUS_LABELS,
    ReservationError,
    apply_status_change,
    available_units,
    expire_due_reservations,
    get_private_settings,
    get_store_settings,
    load_reservation_items,
    log_movement,
    money,
    now_mx,
    sanitize_text,
    serialize_reservation,
    store_settings_public,
    today_mx,
    update_internal_notes_preserving_alert,
    variant_label,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/crm", tags=["crm"])


# La sesión ya carga y valida al administrador activo (ver dependencies/auth.py).
get_admin = get_current_admin_account


class AdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StatusChangeRequest(AdminInput):
    status: str
    note: Optional[str] = ""


class NoteRequest(AdminInput):
    internal_notes: str


class ResendRequest(AdminInput):
    template: str


class ProductPayload(AdminInput):
    name: str
    slug: str
    short_description: Optional[str] = ""
    full_description: Optional[str] = ""
    ingredients: Optional[str] = ""
    usage_instructions: Optional[str] = ""
    category_id: Optional[int] = None
    price: float
    tags: Optional[str] = ""
    is_active: bool = True
    is_featured: bool = False
    is_archived: bool = False
    sort_order: Optional[int] = 0
    images: List[str] = []


class VariantPayload(AdminInput):
    product_id: int
    option_name: Optional[str] = "Presentación"
    option_value: str
    sku: Optional[str] = ""
    # Al editar, None conserva el stock actual: el inventario se cambia con /stock-adjust.
    stock: Optional[int] = None
    price_delta: float = 0
    is_active: bool = True


class StockAdjustRequest(AdminInput):
    variant_id: int
    new_stock: int
    note: Optional[str] = ""


class CategoryPayload(AdminInput):
    name: str
    slug: str
    description: Optional[str] = ""
    image_url: Optional[str] = ""
    sort_order: Optional[int] = 0
    is_active: bool = True


class PointPayload(AdminInput):
    name: str
    kind: Optional[str] = "metro"
    address: Optional[str] = ""
    city: Optional[str] = "Ciudad de México"
    reference: Optional[str] = ""
    notes: Optional[str] = ""
    sort_order: Optional[int] = 0
    is_active: bool = True


HHMM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class SlotPayload(AdminInput):
    delivery_point_id: int
    weekday: int
    # HH:MM con cero inicial, para que comparar texto sea comparar horas.
    start_time: str = Field(pattern=HHMM_PATTERN)
    end_time: str = Field(pattern=HHMM_PATTERN)
    capacity: int = 0
    is_active: bool = True


class StoreSettingsPayload(AdminInput):
    shop_name: str
    tagline: Optional[str] = ""
    logo_url: Optional[str] = ""
    hero_image_url: Optional[str] = ""
    color_bg: Optional[str] = ""
    color_text: Optional[str] = ""
    color_accent: Optional[str] = ""
    contact_email: Optional[str] = ""
    contact_whatsapp: Optional[str] = ""
    instagram_url: Optional[str] = ""
    tiktok_url: Optional[str] = ""
    facebook_url: Optional[str] = ""
    how_it_works: Optional[str] = ""
    faq_content: Optional[str] = ""
    privacy_policy: Optional[str] = ""
    reservation_policy: Optional[str] = ""
    delivery_instructions: Optional[str] = ""
    reservation_window_days: int = 7
    grace_period_hours: int = 2


class PrivateSettingsPayload(AdminInput):
    bank_name: Optional[str] = ""
    account_holder: Optional[str] = ""
    clabe: Optional[str] = ""
    account_number: Optional[str] = ""
    transfer_instructions: Optional[str] = ""
    alert_recipients: Optional[str] = ""
    notification_from_email: Optional[str] = ""
    notification_from_name: Optional[str] = ""


# --------------------------------------------------------------------------- #
# Sesión administrativa
# --------------------------------------------------------------------------- #
@router.get("/session")
async def session_state(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Devuelve el estado de la sesión administrativa autenticada."""
    total = int(
        (await db.execute(select(func.count(Admin_accounts.id)))).scalar() or 0
    )
    result = await db.execute(
        select(Admin_accounts).where(Admin_accounts.auth_user_id == str(current_user.id))
    )
    admin = result.scalars().first()
    return {
        "is_admin": admin is not None and admin.is_active is not False,
        "admin_count": total,
        "role": admin.role if admin else "",
        "name": (admin.name if admin else "") or current_user.name or "",
    }


@router.get("/admins")
async def list_admins(
    admin: Admin_accounts = Depends(get_admin), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    result = await db.execute(select(Admin_accounts).order_by(Admin_accounts.id))
    return {
        "items": [
            {
                "id": a.id,
                "email": a.email or "",
                "name": a.name or "",
                "role": a.role or "staff",
                "is_active": a.is_active is not False,
            }
            for a in result.scalars().all()
        ]
    }


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@router.get("/dashboard")
async def dashboard(
    admin: Admin_accounts = Depends(get_admin), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Métricas operativas del negocio."""
    try:
        await expire_due_reservations(db)
        today = today_mx().isoformat()
        horizon = (today_mx() + timedelta(days=7)).isoformat()

        result = await db.execute(select(Reservations).order_by(Reservations.id.desc()))
        reservations = list(result.scalars().all())

        active = [r for r in reservations if r.status in ACTIVE_STATUSES]
        unread = [r for r in reservations if r.is_unread and r.status in ACTIVE_STATUSES]
        today_deliveries = [r for r in active if (r.delivery_date or "") == today]
        upcoming = [r for r in active if today < (r.delivery_date or "") <= horizon]
        expired = [r for r in reservations if r.status == STATUS_EXPIRED]
        delivered = [r for r in reservations if r.status == STATUS_DELIVERED]

        variants_result = await db.execute(select(Product_variants).order_by(Product_variants.id))
        products_result = await db.execute(select(Products))
        products = {p.id: p for p in products_result.scalars().all()}
        low_stock = []
        for variant in variants_result.scalars().all():
            if variant.is_active is False:
                continue
            units = available_units(variant)
            if units <= 3:
                product = products.get(variant.product_id)
                low_stock.append(
                    {
                        "variant_id": variant.id,
                        "product_id": variant.product_id,
                        "product_name": product.name if product else "Producto",
                        "variant_label": variant_label(variant),
                        "available_units": units,
                        "stock": int(variant.stock or 0),
                        "reserved_stock": int(variant.reserved_stock or 0),
                    }
                )
        low_stock.sort(key=lambda i: i["available_units"])

        history_result = await db.execute(
            select(Reservation_status_history)
            .order_by(Reservation_status_history.id.desc())
            .limit(12)
        )
        folios = {r.id: r.folio for r in reservations}
        activity = [
            {
                "id": h.id,
                "folio": folios.get(h.reservation_id, ""),
                "from_status": h.from_status or "",
                "to_status": h.to_status,
                "to_status_label": STATUS_LABELS.get(h.to_status, h.to_status),
                "note": h.note or "",
                "admin_email": h.admin_email or "",
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in history_result.scalars().all()
        ]

        return {
            "unread_count": len(unread),
            "today_count": len(today_deliveries),
            "upcoming_count": len(upcoming),
            "expired_count": len(expired),
            "expected_total": money(sum(money(r.total_amount) for r in active)),
            "delivered_total": money(sum(money(r.total_amount) for r in delivered)),
            "delivered_count": len(delivered),
            "today_deliveries": [
                {
                    "id": r.id,
                    "folio": r.folio,
                    "customer_name": r.customer_name or "",
                    "delivery_point_name": r.delivery_point_name or "",
                    "slot_start": r.slot_start or "",
                    "slot_end": r.slot_end or "",
                    "total_amount": money(r.total_amount),
                    "status": r.status,
                    "status_label": STATUS_LABELS.get(r.status, r.status),
                }
                for r in sorted(today_deliveries, key=lambda x: x.slot_start or "")
            ],
            "unread": [
                {
                    "id": r.id,
                    "folio": r.folio,
                    "customer_name": r.customer_name or "",
                    "total_amount": money(r.total_amount),
                    "delivery_date": r.delivery_date or "",
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in unread[:8]
            ],
            "low_stock": low_stock[:10],
            "activity": activity,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en dashboard: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos cargar el panel.")


# --------------------------------------------------------------------------- #
# Reservaciones
# --------------------------------------------------------------------------- #
def _matches_search(reservation: Reservations, needle: str) -> bool:
    if not needle:
        return True
    haystack = " ".join(
        [
            reservation.folio or "",
            reservation.customer_name or "",
            reservation.customer_whatsapp or "",
            reservation.customer_email or "",
        ]
    ).lower()
    return needle in haystack


def _filter_reservations(
    reservations: List[Reservations],
    *,
    search: str,
    status: str,
    delivery_point_id: int,
    date_from: str,
    date_to: str,
) -> List[Reservations]:
    """Filtros compartidos por la lista del CRM y la exportación CSV."""
    needle = (search or "").strip().lower()
    return [
        r
        for r in reservations
        if (not status or r.status == status)
        and (not delivery_point_id or r.delivery_point_id == delivery_point_id)
        and (not date_from or (r.delivery_date or "") >= date_from)
        and (not date_to or (r.delivery_date or "") <= date_to)
        and _matches_search(r, needle)
    ]


@router.get("/reservations")
async def list_reservations(
    search: str = "",
    status: str = "",
    delivery_point_id: int = 0,
    date_from: str = "",
    date_to: str = "",
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        await expire_due_reservations(db)
        result = await db.execute(select(Reservations).order_by(Reservations.id.desc()))
        filtered = _filter_reservations(
            list(result.scalars().all()),
            search=search,
            status=status,
            delivery_point_id=delivery_point_id,
            date_from=date_from,
            date_to=date_to,
        )

        return {
            "items": [
                {
                    "id": r.id,
                    "folio": r.folio,
                    "status": r.status,
                    "status_label": STATUS_LABELS.get(r.status, r.status),
                    "customer_name": r.customer_name or "",
                    "customer_whatsapp": r.customer_whatsapp or "",
                    "customer_email": r.customer_email or "",
                    "delivery_point_name": r.delivery_point_name or "",
                    "delivery_point_id": r.delivery_point_id,
                    "delivery_date": r.delivery_date or "",
                    "slot_start": r.slot_start or "",
                    "slot_end": r.slot_end or "",
                    "total_amount": money(r.total_amount),
                    "item_count": int(r.item_count or 0),
                    "is_unread": bool(r.is_unread),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in filtered
            ],
            "total": len(filtered),
            "statuses": [{"value": s, "label": STATUS_LABELS[s]} for s in ALL_STATUSES],
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Error listando reservaciones: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos cargar las reservaciones.")


@router.get("/reservations/{reservation_id}")
async def reservation_detail(
    reservation_id: int,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    reservation = (
        await db.execute(select(Reservations).where(Reservations.id == reservation_id))
    ).scalars().first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    items = await load_reservation_items(db, reservation.id)
    history_result = await db.execute(
        select(Reservation_status_history)
        .where(Reservation_status_history.reservation_id == reservation.id)
        .order_by(Reservation_status_history.id.desc())
    )
    notifications = await mailer.notification_log(db, reservation.id)
    return {
        "reservation": serialize_reservation(reservation, items),
        "history": [
            {
                "id": h.id,
                "from_status": h.from_status or "",
                "to_status": h.to_status,
                "to_status_label": STATUS_LABELS.get(h.to_status, h.to_status),
                "admin_email": h.admin_email or "",
                "note": h.note or "",
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in history_result.scalars().all()
        ],
        "notifications": notifications,
        "statuses": [{"value": s, "label": STATUS_LABELS[s]} for s in ALL_STATUSES],
    }


@router.post("/reservations/{reservation_id}/read")
async def mark_read(
    reservation_id: int,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    reservation = (
        await db.execute(select(Reservations).where(Reservations.id == reservation_id))
    ).scalars().first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    reservation.is_unread = False
    await db.commit()
    return {"id": reservation_id, "is_unread": False}


@router.post("/reservations/{reservation_id}/status")
async def change_status(
    reservation_id: int,
    data: StatusChangeRequest,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Cambia el estado, ajusta el inventario y envía el correo correspondiente."""
    reservation = (
        await db.execute(select(Reservations).where(Reservations.id == reservation_id))
    ).scalars().first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    try:
        await apply_status_change(
            db,
            reservation,
            data.status,
            admin_user_id=str(admin.auth_user_id),
            admin_email=admin.email or "",
            note=sanitize_text(data.note, 400),
        )
    except ReservationError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=exc.message)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error("Error cambiando estado: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="No pudimos actualizar el estado.")

    email_results: List[Dict[str, Any]] = []
    template = mailer.status_template(data.status)
    if template:
        try:
            email_results = await mailer.dispatch_reservation_emails(
                db,
                reservation_id,
                [template],
                app_host=app_settings.public_site_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Fallo de correo al cambiar estado: %s", exc, exc_info=True)

    items = await load_reservation_items(db, reservation_id)
    refreshed = (
        await db.execute(select(Reservations).where(Reservations.id == reservation_id))
    ).scalars().first()
    return {
        "reservation": serialize_reservation(refreshed, items),
        "email_status": email_results,
    }


@router.post("/reservations/{reservation_id}/note")
async def save_note(
    reservation_id: int,
    data: NoteRequest,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    reservation = (
        await db.execute(select(Reservations).where(Reservations.id == reservation_id))
    ).scalars().first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    update_internal_notes_preserving_alert(reservation, data.internal_notes)
    await db.commit()
    return {"id": reservation_id, "internal_notes": reservation.internal_notes}


@router.post("/reservations/{reservation_id}/resend")
async def resend_email(
    reservation_id: int,
    data: ResendRequest,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Reenvía manualmente un correo y actualiza su estado real en la bitácora."""
    reservation = (
        await db.execute(select(Reservations).where(Reservations.id == reservation_id))
    ).scalars().first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    template = data.template
    if template not in mailer.CUSTOMER_TEMPLATES and template != mailer.TEMPLATE_BUSINESS_ALERT:
        raise HTTPException(status_code=400, detail="Plantilla de correo no válida.")
    if template in {
        mailer.TEMPLATE_RECEIVED,
        mailer.TEMPLATE_CONFIRMED,
        mailer.TEMPLATE_READY,
        mailer.TEMPLATE_PRIVATE_LINK,
    }:
        raise HTTPException(
            status_code=400,
            detail="Genera un enlace privado nuevo para enviar este correo con una confirmación utilizable.",
        )

    results = await mailer.dispatch_reservation_emails(
        db,
        reservation_id,
        [template],
        app_host=app_settings.public_site_url,
        force=True,
    )
    return {
        "email_status": results,
        "notifications": await mailer.notification_log(db, reservation_id),
    }


@router.post("/reservations/{reservation_id}/rotate-confirmation-token")
async def rotate_confirmation_token(
    reservation_id: int,
    response: Response,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Rotate, send and return one replacement capability exactly once."""
    reservation = (
        await db.execute(select(Reservations).where(Reservations.id == reservation_id).with_for_update())
    ).scalars().first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    if reservation.status not in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Los apartados en estado terminal no pueden generar enlaces privados nuevos.",
        )
    raw_token = new_secret_token()
    reservation.private_token_hash = private_token_hash(raw_token)
    reservation.token_revoked = False
    await db.commit()

    try:
        email_results = await mailer.dispatch_reservation_emails(
            db,
            reservation_id,
            [mailer.TEMPLATE_PRIVATE_LINK],
            app_host=app_settings.public_site_url,
            force=True,
            confirmation_token=raw_token,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Fallo inesperado al enviar un enlace privado nuevo (%s)",
            type(exc).__name__,
        )
        email_results = [
            {
                "template": mailer.TEMPLATE_PRIVATE_LINK,
                "status": "fallido",
                "error": "El proveedor no confirmó el envío.",
            }
        ]

    email_sent = any(result.get("status") == "enviado" for result in email_results)
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        }
    )
    return {
        "private_token": raw_token,
        "email_sent": email_sent,
        "recovery_required": not email_sent,
        "email_status": email_results,
        "notifications": await mailer.notification_log(db, reservation_id),
        "message": (
            "El enlace nuevo se envió y el anterior quedó invalidado."
            if email_sent
            else "El correo no se confirmó. Copia el enlace nuevo antes de cerrar este panel."
        ),
    }


@router.post("/reservations/{reservation_id}/revoke-confirmation-token")
async def revoke_confirmation_token(
    reservation_id: int,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Explicitly revoke a private confirmation capability without deleting data."""

    reservation = (
        await db.execute(select(Reservations).where(Reservations.id == reservation_id).with_for_update())
    ).scalars().first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    reservation.token_revoked = True
    await db.commit()
    return {"revoked": True, "message": "El enlace privado quedó revocado."}


@router.get("/reservations-export")
async def export_reservations(
    search: str = "",
    status: str = "",
    delivery_point_id: int = 0,
    date_from: str = "",
    date_to: str = "",
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Devuelve las reservaciones filtradas en formato CSV listo para descargar."""
    result = await db.execute(select(Reservations).order_by(Reservations.id.desc()))
    filtered = _filter_reservations(
        list(result.scalars().all()),
        search=search,
        status=status,
        delivery_point_id=delivery_point_id,
        date_from=date_from,
        date_to=date_to,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Folio",
            "Estado",
            "Clienta",
            "WhatsApp",
            "Correo",
            "Punto de entrega",
            "Fecha",
            "Horario",
            "Artículos",
            "Total MXN",
            "Notas de la clienta",
            "Notas internas",
            "Creada",
        ]
    )
    for r in filtered:
        writer.writerow(
            [
                r.folio,
                STATUS_LABELS.get(r.status, r.status),
                sanitize_csv_text(r.customer_name),
                sanitize_csv_text(r.customer_whatsapp),
                sanitize_csv_text(r.customer_email),
                sanitize_csv_text(r.delivery_point_name),
                r.delivery_date or "",
                sanitize_csv_text(f"{r.slot_start or ''} a {r.slot_end or ''}"),
                int(r.item_count or 0),
                money(r.total_amount),
                sanitize_csv_text((r.customer_notes or "").replace("\r", " ").replace("\n", " ")),
                sanitize_csv_text((r.internal_notes or "").replace("\r", " ").replace("\n", " ")),
                r.created_at.isoformat() if r.created_at else "",
            ]
        )

    filename = f"reservaciones-{now_mx().strftime('%Y%m%d-%H%M')}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Exported-Rows": str(len(filtered)),
        },
    )


@router.get("/failed-emails")
async def failed_emails(
    admin: Admin_accounts = Depends(get_admin), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Correos fallidos o pendientes para que el administrador pueda reenviarlos."""
    from models.notifications import Notifications

    result = await db.execute(
        select(Notifications)
        .where(Notifications.status.in_(["fallido", "pendiente"]))
        .order_by(Notifications.id.desc())
        .limit(50)
    )
    notifications = list(result.scalars().all())
    reservation_ids = {n.reservation_id for n in notifications if n.reservation_id}
    folios: Dict[int, str] = {}
    if reservation_ids:
        folio_result = await db.execute(
            select(Reservations.id, Reservations.folio).where(Reservations.id.in_(reservation_ids))
        )
        folios = {row[0]: row[1] for row in folio_result.all()}
    return {
        "items": [
            {
                "id": n.id,
                "reservation_id": n.reservation_id,
                "folio": folios.get(n.reservation_id, ""),
                "recipient_type": n.recipient_type,
                "recipient_email": n.recipient_email or "",
                "template": n.template,
                "status": n.status,
                "error_message": n.error_message or "",
                "attempts": int(n.attempts or 0),
            }
            for n in notifications
        ]
    }


# --------------------------------------------------------------------------- #
# Fotos
# --------------------------------------------------------------------------- #
# El navegador reduce las fotos antes de subirlas; este tope sólo frena abusos.
MAX_UPLOAD_BYTES = 3 * 1024 * 1024


def _image_content_type(data: bytes) -> Optional[str]:
    """Detecta el formato por su firma; nunca confía en el Content-Type del cliente."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.post("/uploads")
async def upload_image(
    request: Request,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="La foto pesa más de 3 MB.")
    content_type = _image_content_type(bytes(data))
    if content_type is None:
        raise HTTPException(status_code=400, detail="Sube una foto JPG, PNG o WebP.")
    image = Uploaded_images(content_type=content_type, size_bytes=len(data), data=bytes(data))
    db.add(image)
    await db.commit()
    return {"url": f"/api/v1/shop/images/{image.id}"}


# --------------------------------------------------------------------------- #
# Catálogo
# --------------------------------------------------------------------------- #
@router.get("/catalog")
async def catalog(
    admin: Admin_accounts = Depends(get_admin), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    products_result = await db.execute(select(Products).order_by(Products.sort_order, Products.id))
    products = list(products_result.scalars().all())
    categories_result = await db.execute(select(Categories).order_by(Categories.sort_order, Categories.id))
    categories = list(categories_result.scalars().all())

    ids = [p.id for p in products]
    variants_map: Dict[int, List[Product_variants]] = {}
    images_map: Dict[int, List[Product_images]] = {}
    if ids:
        variants_result = await db.execute(
            select(Product_variants).where(Product_variants.product_id.in_(ids)).order_by(Product_variants.id)
        )
        for v in variants_result.scalars().all():
            variants_map.setdefault(v.product_id, []).append(v)
        images_result = await db.execute(
            select(Product_images)
            .where(Product_images.product_id.in_(ids))
            .order_by(Product_images.sort_order, Product_images.id)
        )
        for i in images_result.scalars().all():
            images_map.setdefault(i.product_id, []).append(i)

    return {
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "slug": c.slug,
                "description": c.description or "",
                "image_url": c.image_url or "",
                "sort_order": int(c.sort_order or 0),
                "is_active": c.is_active is not False,
            }
            for c in categories
        ],
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "short_description": p.short_description or "",
                "full_description": p.full_description or "",
                "ingredients": p.ingredients or "",
                "usage_instructions": p.usage_instructions or "",
                "category_id": p.category_id,
                "price": money(p.price),
                "tags": p.tags or "",
                "is_active": p.is_active is not False,
                "is_featured": bool(p.is_featured),
                "is_archived": bool(p.is_archived),
                "sort_order": int(p.sort_order or 0),
                "images": [
                    {"id": i.id, "url": i.url, "alt_text": i.alt_text or ""}
                    for i in images_map.get(p.id, [])
                ],
                "variants": [
                    {
                        "id": v.id,
                        "option_name": v.option_name or "",
                        "option_value": v.option_value,
                        "label": variant_label(v),
                        "sku": v.sku or "",
                        "stock": int(v.stock or 0),
                        "reserved_stock": int(v.reserved_stock or 0),
                        "available_units": available_units(v),
                        "price_delta": money(v.price_delta),
                        "is_active": v.is_active is not False,
                    }
                    for v in variants_map.get(p.id, [])
                ],
            }
            for p in products
        ],
    }


@router.post("/products")
async def create_product(
    data: ProductPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    exists = await db.execute(select(Products.id).where(Products.slug == data.slug))
    if exists.scalars().first() is not None:
        raise HTTPException(status_code=400, detail="Ya existe un producto con ese slug.")
    product = Products(
        name=sanitize_text(data.name, 160),
        slug=sanitize_text(data.slug, 160),
        short_description=sanitize_text(data.short_description, 300),
        full_description=sanitize_text(data.full_description, 4000),
        ingredients=sanitize_text(data.ingredients, 2000),
        usage_instructions=sanitize_text(data.usage_instructions, 2000),
        category_id=data.category_id,
        price=money(data.price),
        tags=sanitize_text(data.tags, 300),
        is_active=data.is_active,
        is_featured=data.is_featured,
        is_archived=data.is_archived,
        sort_order=int(data.sort_order or 0),
    )
    db.add(product)
    await db.flush()
    for index, url in enumerate(data.images):
        clean = sanitize_text(url, 600)
        if clean:
            db.add(
                Product_images(
                    product_id=product.id, url=clean, alt_text=product.name, sort_order=index + 1
                )
            )
    await db.commit()
    return {"id": product.id, "slug": product.slug}


@router.put("/products/{product_id}")
async def update_product(
    product_id: int,
    data: ProductPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    product = (
        await db.execute(select(Products).where(Products.id == product_id))
    ).scalars().first()
    if product is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    duplicate = await db.execute(
        select(Products.id).where(Products.slug == data.slug, Products.id != product_id)
    )
    if duplicate.scalars().first() is not None:
        raise HTTPException(status_code=400, detail="Ya existe otro producto con ese slug.")

    product.name = sanitize_text(data.name, 160)
    product.slug = sanitize_text(data.slug, 160)
    product.short_description = sanitize_text(data.short_description, 300)
    product.full_description = sanitize_text(data.full_description, 4000)
    product.ingredients = sanitize_text(data.ingredients, 2000)
    product.usage_instructions = sanitize_text(data.usage_instructions, 2000)
    product.category_id = data.category_id
    product.price = money(data.price)
    product.tags = sanitize_text(data.tags, 300)
    product.is_active = data.is_active
    product.is_featured = data.is_featured
    product.is_archived = data.is_archived
    product.sort_order = int(data.sort_order or 0)

    # El CRM siempre envía la lista completa, en orden; la primera es la principal.
    current = await db.execute(
        select(Product_images).where(Product_images.product_id == product_id)
    )
    for image in current.scalars().all():
        await db.delete(image)
    for index, url in enumerate(data.images):
        clean = sanitize_text(url, 600)
        if clean:
            db.add(
                Product_images(
                    product_id=product_id, url=clean, alt_text=product.name, sort_order=index + 1
                )
            )
    await db.commit()
    return {"id": product_id, "slug": product.slug}


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: int,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Elimina el producto. Se bloquea si tiene apartados activos."""
    product = (
        await db.execute(select(Products).where(Products.id == product_id))
    ).scalars().first()
    if product is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    variants_result = await db.execute(
        select(Product_variants).where(Product_variants.product_id == product_id)
    )
    variants = list(variants_result.scalars().all())
    if any(int(v.reserved_stock or 0) > 0 for v in variants):
        raise HTTPException(
            status_code=400,
            detail="Este producto tiene piezas apartadas. Archívalo en lugar de eliminarlo.",
        )

    for variant in variants:
        await db.delete(variant)
    images_result = await db.execute(
        select(Product_images).where(Product_images.product_id == product_id)
    )
    for image in images_result.scalars().all():
        await db.delete(image)
    await db.delete(product)
    await db.commit()
    return {"id": product_id, "deleted": True}


@router.post("/variants")
async def create_variant(
    data: VariantPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    variant = Product_variants(
        product_id=data.product_id,
        option_name=sanitize_text(data.option_name, 60) or "Presentación",
        option_value=sanitize_text(data.option_value, 80),
        sku=sanitize_text(data.sku, 60),
        stock=max(0, int(data.stock or 0)),
        reserved_stock=0,
        price_delta=money(data.price_delta),
        is_active=data.is_active,
    )
    db.add(variant)
    await db.flush()
    if variant.stock > 0:
        await log_movement(
            db,
            variant=variant,
            product_id=data.product_id,
            reservation_id=None,
            movement_type="entrada",
            quantity=variant.stock,
            note="Alta de variante desde el panel",
            admin_user_id=str(admin.auth_user_id),
        )
    await db.commit()
    return {"id": variant.id}


@router.put("/variants/{variant_id}")
async def update_variant(
    variant_id: int,
    data: VariantPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    variant = (
        await db.execute(select(Product_variants).where(Product_variants.id == variant_id))
    ).scalars().first()
    if variant is None:
        raise HTTPException(status_code=404, detail="Variante no encontrada")

    new_stock = int(variant.stock or 0) if data.stock is None else max(0, int(data.stock))
    delta = new_stock - int(variant.stock or 0)
    variant.option_name = sanitize_text(data.option_name, 60) or "Presentación"
    variant.option_value = sanitize_text(data.option_value, 80)
    variant.sku = sanitize_text(data.sku, 60)
    variant.price_delta = money(data.price_delta)
    variant.is_active = data.is_active
    if new_stock < int(variant.reserved_stock or 0):
        raise HTTPException(
            status_code=400,
            detail=f"No puedes dejar menos de {int(variant.reserved_stock or 0)} piezas: ya están apartadas.",
        )
    variant.stock = new_stock
    if delta != 0:
        await log_movement(
            db,
            variant=variant,
            product_id=variant.product_id,
            reservation_id=None,
            movement_type="ajuste",
            quantity=abs(delta),
            note=f"Ajuste manual desde el panel ({'+' if delta > 0 else '-'}{abs(delta)})",
            admin_user_id=str(admin.auth_user_id),
        )
    await db.commit()
    return {"id": variant_id, "stock": variant.stock}


@router.delete("/variants/{variant_id}")
async def delete_variant(
    variant_id: int,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    variant = (
        await db.execute(select(Product_variants).where(Product_variants.id == variant_id))
    ).scalars().first()
    if variant is None:
        raise HTTPException(status_code=404, detail="Variante no encontrada")
    if int(variant.reserved_stock or 0) > 0:
        raise HTTPException(
            status_code=400, detail="Esta variante tiene piezas apartadas. Desactívala en lugar de borrarla."
        )
    await db.delete(variant)
    await db.commit()
    return {"id": variant_id, "deleted": True}


@router.post("/stock-adjust")
async def adjust_stock(
    data: StockAdjustRequest,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Ajuste manual de inventario con historial."""
    variant = (
        await db.execute(select(Product_variants).where(Product_variants.id == data.variant_id))
    ).scalars().first()
    if variant is None:
        raise HTTPException(status_code=404, detail="Variante no encontrada")
    new_stock = max(0, int(data.new_stock))
    if new_stock < int(variant.reserved_stock or 0):
        raise HTTPException(
            status_code=400,
            detail=f"Hay {int(variant.reserved_stock or 0)} piezas apartadas. No puedes bajar de ese número.",
        )
    delta = new_stock - int(variant.stock or 0)
    if delta == 0:
        return {"id": variant.id, "stock": variant.stock, "available_units": available_units(variant)}
    variant.stock = new_stock
    await log_movement(
        db,
        variant=variant,
        product_id=variant.product_id,
        reservation_id=None,
        movement_type="ajuste",
        quantity=abs(delta),
        note=sanitize_text(data.note, 300) or "Ajuste manual de inventario",
        admin_user_id=str(admin.auth_user_id),
    )
    await db.commit()
    return {"id": variant.id, "stock": variant.stock, "available_units": available_units(variant)}


@router.get("/inventory-movements")
async def inventory_movements(
    variant_id: int = 0,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    query = select(Inventory_movements).order_by(Inventory_movements.id.desc()).limit(60)
    if variant_id:
        query = (
            select(Inventory_movements)
            .where(Inventory_movements.variant_id == variant_id)
            .order_by(Inventory_movements.id.desc())
            .limit(60)
        )
    result = await db.execute(query)
    return {
        "items": [
            {
                "id": m.id,
                "variant_id": m.variant_id,
                "product_id": m.product_id,
                "reservation_id": m.reservation_id,
                "movement_type": m.movement_type,
                "quantity": int(m.quantity or 0),
                "stock_after": m.stock_after,
                "reserved_after": m.reserved_after,
                "note": m.note or "",
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in result.scalars().all()
        ]
    }


@router.post("/categories")
async def create_category(
    data: CategoryPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    exists = await db.execute(select(Categories.id).where(Categories.slug == data.slug))
    if exists.scalars().first() is not None:
        raise HTTPException(status_code=400, detail="Ya existe una categoría con ese slug.")
    category = Categories(
        name=sanitize_text(data.name, 120),
        slug=sanitize_text(data.slug, 120),
        description=sanitize_text(data.description, 400),
        image_url=sanitize_text(data.image_url, 600),
        sort_order=int(data.sort_order or 0),
        is_active=data.is_active,
    )
    db.add(category)
    await db.commit()
    return {"id": category.id}


@router.put("/categories/{category_id}")
async def update_category(
    category_id: int,
    data: CategoryPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    category = (
        await db.execute(select(Categories).where(Categories.id == category_id))
    ).scalars().first()
    if category is None:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    category.name = sanitize_text(data.name, 120)
    category.slug = sanitize_text(data.slug, 120)
    category.description = sanitize_text(data.description, 400)
    category.image_url = sanitize_text(data.image_url, 600)
    category.sort_order = int(data.sort_order or 0)
    category.is_active = data.is_active
    await db.commit()
    return {"id": category_id}


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    category = (
        await db.execute(select(Categories).where(Categories.id == category_id))
    ).scalars().first()
    if category is None:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    used = await db.execute(select(Products.id).where(Products.category_id == category_id).limit(1))
    if used.scalars().first() is not None:
        raise HTTPException(
            status_code=400, detail="Hay productos en esta categoría. Reasígnalos antes de eliminarla."
        )
    await db.delete(category)
    await db.commit()
    return {"id": category_id, "deleted": True}


# --------------------------------------------------------------------------- #
# Puntos de entrega y horarios
# --------------------------------------------------------------------------- #
@router.get("/delivery")
async def delivery_config(
    admin: Admin_accounts = Depends(get_admin), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    points_result = await db.execute(
        select(Delivery_points).order_by(Delivery_points.sort_order, Delivery_points.id)
    )
    points = list(points_result.scalars().all())
    slots_result = await db.execute(
        select(Delivery_slots).order_by(Delivery_slots.weekday, Delivery_slots.start_time)
    )
    slots = list(slots_result.scalars().all())
    return {
        "points": [
            {
                "id": p.id,
                "name": p.name,
                "kind": p.kind or "",
                "address": p.address or "",
                "city": p.city or "",
                "reference": p.reference or "",
                "notes": p.notes or "",
                "sort_order": int(p.sort_order or 0),
                "is_active": p.is_active is not False,
            }
            for p in points
        ],
        "slots": [
            {
                "id": s.id,
                "delivery_point_id": s.delivery_point_id,
                "weekday": int(s.weekday),
                "start_time": s.start_time,
                "end_time": s.end_time,
                "capacity": int(s.capacity or 0),
                "is_active": s.is_active is not False,
            }
            for s in slots
        ],
    }


@router.post("/delivery-points")
async def create_point(
    data: PointPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    point = Delivery_points(
        name=sanitize_text(data.name, 140),
        kind=sanitize_text(data.kind, 40),
        address=sanitize_text(data.address, 300),
        city=sanitize_text(data.city, 120),
        reference=sanitize_text(data.reference, 300),
        notes=sanitize_text(data.notes, 400),
        sort_order=int(data.sort_order or 0),
        is_active=data.is_active,
    )
    db.add(point)
    await db.commit()
    return {"id": point.id}


@router.put("/delivery-points/{point_id}")
async def update_point(
    point_id: int,
    data: PointPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    point = (
        await db.execute(select(Delivery_points).where(Delivery_points.id == point_id))
    ).scalars().first()
    if point is None:
        raise HTTPException(status_code=404, detail="Punto de entrega no encontrado")
    point.name = sanitize_text(data.name, 140)
    point.kind = sanitize_text(data.kind, 40)
    point.address = sanitize_text(data.address, 300)
    point.city = sanitize_text(data.city, 120)
    point.reference = sanitize_text(data.reference, 300)
    point.notes = sanitize_text(data.notes, 400)
    point.sort_order = int(data.sort_order or 0)
    point.is_active = data.is_active
    await db.commit()
    return {"id": point_id}


@router.delete("/delivery-points/{point_id}")
async def delete_point(
    point_id: int,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    point = (
        await db.execute(select(Delivery_points).where(Delivery_points.id == point_id))
    ).scalars().first()
    if point is None:
        raise HTTPException(status_code=404, detail="Punto de entrega no encontrado")
    active = await db.execute(
        select(Reservations.id)
        .where(Reservations.delivery_point_id == point_id, Reservations.status.in_(ACTIVE_STATUSES))
        .limit(1)
    )
    if active.scalars().first() is not None:
        raise HTTPException(
            status_code=400, detail="Hay apartados activos en este punto. Desactívalo en lugar de borrarlo."
        )
    slots = await db.execute(select(Delivery_slots).where(Delivery_slots.delivery_point_id == point_id))
    for slot in slots.scalars().all():
        await db.delete(slot)
    await db.delete(point)
    await db.commit()
    return {"id": point_id, "deleted": True}


@router.post("/delivery-slots")
async def create_slot(
    data: SlotPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if data.start_time >= data.end_time:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser menor que la de fin.")
    slot = Delivery_slots(
        delivery_point_id=data.delivery_point_id,
        weekday=max(0, min(6, int(data.weekday))),
        start_time=sanitize_text(data.start_time, 5),
        end_time=sanitize_text(data.end_time, 5),
        capacity=max(0, int(data.capacity)),
        is_active=data.is_active,
    )
    db.add(slot)
    await db.commit()
    return {"id": slot.id}


@router.put("/delivery-slots/{slot_id}")
async def update_slot(
    slot_id: int,
    data: SlotPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    slot = (
        await db.execute(select(Delivery_slots).where(Delivery_slots.id == slot_id))
    ).scalars().first()
    if slot is None:
        raise HTTPException(status_code=404, detail="Horario no encontrado")
    if data.start_time >= data.end_time:
        raise HTTPException(status_code=400, detail="La hora de inicio debe ser menor que la de fin.")
    slot.delivery_point_id = data.delivery_point_id
    slot.weekday = max(0, min(6, int(data.weekday)))
    slot.start_time = sanitize_text(data.start_time, 5)
    slot.end_time = sanitize_text(data.end_time, 5)
    slot.capacity = max(0, int(data.capacity))
    slot.is_active = data.is_active
    await db.commit()
    return {"id": slot_id}


@router.delete("/delivery-slots/{slot_id}")
async def delete_slot(
    slot_id: int,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    slot = (
        await db.execute(select(Delivery_slots).where(Delivery_slots.id == slot_id))
    ).scalars().first()
    if slot is None:
        raise HTTPException(status_code=404, detail="Horario no encontrado")
    await db.delete(slot)
    await db.commit()
    return {"id": slot_id, "deleted": True}


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
@router.get("/settings")
async def read_settings(
    admin: Admin_accounts = Depends(get_admin), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    settings = await get_store_settings(db)
    private = await get_private_settings(db)
    return {
        "store": store_settings_public(settings),
        "private": {
            "bank_name": (private.bank_name if private else "") or "",
            "account_holder": (private.account_holder if private else "") or "",
            "clabe": (private.clabe if private else "") or "",
            "account_number": (private.account_number if private else "") or "",
            "transfer_instructions": (private.transfer_instructions if private else "") or "",
            "alert_recipients": (private.alert_recipients if private else "") or "",
            "notification_from_email": (private.notification_from_email if private else "") or "",
            "notification_from_name": (private.notification_from_name if private else "") or "",
        },
        "email_provider_configured": bool(app_settings.resend_api_key.strip()),
    }


@router.put("/settings/store")
async def update_store_settings(
    data: StoreSettingsPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    settings = await get_store_settings(db)
    if settings is None:
        settings = Store_settings(shop_name=sanitize_text(data.shop_name, 120))
        db.add(settings)
    settings.shop_name = sanitize_text(data.shop_name, 120) or "Nébula Beauty MX"
    settings.tagline = sanitize_text(data.tagline, 160)
    settings.logo_url = sanitize_text(data.logo_url, 600)
    settings.hero_image_url = sanitize_text(data.hero_image_url, 600)
    settings.color_bg = sanitize_text(data.color_bg, 20)
    settings.color_text = sanitize_text(data.color_text, 20)
    settings.color_accent = sanitize_text(data.color_accent, 20)
    settings.contact_email = sanitize_text(data.contact_email, 160)
    settings.contact_whatsapp = sanitize_text(data.contact_whatsapp, 20)
    settings.instagram_url = sanitize_text(data.instagram_url, 300)
    settings.tiktok_url = sanitize_text(data.tiktok_url, 300)
    settings.facebook_url = sanitize_text(data.facebook_url, 300)
    settings.how_it_works = sanitize_text(data.how_it_works, 6000)
    settings.faq_content = sanitize_text(data.faq_content, 8000)
    settings.privacy_policy = sanitize_text(data.privacy_policy, 12000)
    settings.reservation_policy = sanitize_text(data.reservation_policy, 12000)
    settings.delivery_instructions = sanitize_text(data.delivery_instructions, 2000)
    settings.reservation_window_days = max(1, min(60, int(data.reservation_window_days)))
    settings.grace_period_hours = max(0, min(72, int(data.grace_period_hours)))
    settings.is_active = True
    await db.commit()
    return {"saved": True}


@router.put("/settings/private")
async def update_private_settings(
    data: PrivateSettingsPayload,
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    private = await get_private_settings(db)
    if private is None:
        private = Private_settings()
        db.add(private)
    private.bank_name = sanitize_text(data.bank_name, 120)
    private.account_holder = sanitize_text(data.account_holder, 160)
    private.clabe = sanitize_text(data.clabe, 40)
    private.account_number = sanitize_text(data.account_number, 40)
    private.transfer_instructions = sanitize_text(data.transfer_instructions, 2000)
    private.alert_recipients = sanitize_text(data.alert_recipients, 500)
    private.notification_from_email = sanitize_text(data.notification_from_email, 160)
    private.notification_from_name = sanitize_text(data.notification_from_name, 120)
    await db.commit()
    return {"saved": True}


@router.get("/customers")
async def list_customers(
    search: str = "",
    admin: Admin_accounts = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    result = await db.execute(select(Customers).order_by(Customers.id.desc()).limit(200))
    needle = (search or "").strip().lower()
    items = []
    for c in result.scalars().all():
        haystack = f"{c.full_name or ''} {c.whatsapp or ''} {c.email or ''}".lower()
        if needle and needle not in haystack:
            continue
        items.append(
            {
                "id": c.id,
                "full_name": c.full_name or "",
                "whatsapp": c.whatsapp or "",
                "email": c.email or "",
                "reservation_count": int(c.reservation_count or 0),
                "delivered_count": int(c.delivered_count or 0),
            }
        )
    return {"items": items, "total": len(items)}
