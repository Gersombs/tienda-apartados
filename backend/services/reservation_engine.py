"""Motor de apartado, inventario y vencimientos para Nébula Beauty MX.

Reglas centrales:
- `disponible = stock - reserved_stock`.
- Crear una reservación incrementa `reserved_stock` dentro de una transacción con
  bloqueo `SELECT ... FOR UPDATE` sobre las variantes, lo que impide sobreventa.
- Cancelar, marcar "no se presentó" o vencer libera `reserved_stock`.
- Marcar como entregada convierte la reserva en salida definitiva de `stock`.
"""

import asyncio
import logging
import re
import secrets
import string
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import new_secret_token, private_token_hash
from core.reservation_limits import (
    MAX_RESERVATION_LINES,
    MAX_RESERVATION_TOTAL_UNITS,
    MAX_RESERVATION_UNITS_PER_LINE,
)
from core.time_utils import as_utc, utc_now

from models.customers import Customers
from models.delivery_points import Delivery_points
from models.delivery_slots import Delivery_slots
from models.inventory_movements import Inventory_movements
from models.private_settings import Private_settings
from models.product_images import Product_images
from models.product_variants import Product_variants
from models.products import Products
from models.reservation_items import Reservation_items
from models.reservation_status_history import Reservation_status_history
from models.reservations import Reservations
from models.store_settings import Store_settings

logger = logging.getLogger(__name__)
SQLITE_RESERVATION_LOCK = asyncio.Lock()

# Ciudad de México ya no aplica horario de verano: UTC-6 fijo.
MX_TZ = timezone(timedelta(hours=-6))

STATUS_RECEIVED = "recibida"
STATUS_CONFIRMED = "confirmada"
STATUS_PREPARING = "preparando"
STATUS_READY = "lista"
STATUS_DELIVERED = "entregada"
STATUS_CANCELLED = "cancelada"
STATUS_NO_SHOW = "no_show"
STATUS_EXPIRED = "vencida"

ALL_STATUSES = [
    STATUS_RECEIVED,
    STATUS_CONFIRMED,
    STATUS_PREPARING,
    STATUS_READY,
    STATUS_DELIVERED,
    STATUS_CANCELLED,
    STATUS_NO_SHOW,
    STATUS_EXPIRED,
]

STATUS_LABELS = {
    STATUS_RECEIVED: "Recibida",
    STATUS_CONFIRMED: "Confirmada",
    STATUS_PREPARING: "Preparando",
    STATUS_READY: "Lista para entregar",
    STATUS_DELIVERED: "Entregada",
    STATUS_CANCELLED: "Cancelada",
    STATUS_NO_SHOW: "No se presentó",
    STATUS_EXPIRED: "Vencida",
}

# Estados que mantienen unidades apartadas fuera de la disponibilidad pública.
ACTIVE_STATUSES = (STATUS_RECEIVED, STATUS_CONFIRMED, STATUS_PREPARING, STATUS_READY)
# Estados que liberan el inventario apartado.
RELEASING_STATUSES = (STATUS_CANCELLED, STATUS_NO_SHOW, STATUS_EXPIRED)

ALLOWED_TRANSITIONS = {
    STATUS_RECEIVED: {STATUS_CONFIRMED, STATUS_PREPARING, STATUS_READY, STATUS_CANCELLED, STATUS_EXPIRED},
    STATUS_CONFIRMED: {STATUS_PREPARING, STATUS_READY, STATUS_CANCELLED, STATUS_NO_SHOW, STATUS_EXPIRED},
    STATUS_PREPARING: {STATUS_READY, STATUS_CANCELLED, STATUS_NO_SHOW, STATUS_EXPIRED},
    STATUS_READY: {STATUS_DELIVERED, STATUS_CANCELLED, STATUS_NO_SHOW, STATUS_EXPIRED},
    STATUS_DELIVERED: set(),
    STATUS_CANCELLED: set(),
    STATUS_NO_SHOW: set(),
    # Se entregó pero nadie lo marcó a tiempo: aún puede registrarse la entrega.
    STATUS_EXPIRED: {STATUS_DELIVERED},
}

WEEKDAY_LABELS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

FOLIO_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
CANONICAL_EXPIRATION_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)

DEFAULT_WINDOW_DAYS = 7
DEFAULT_GRACE_HOURS = 2
MAX_ADMIN_INTERNAL_NOTES = 2000
EXPIRATION_ALERT_MARKER = "[ALERTA OPERATIVA: VENCIMIENTO INVÁLIDO]"
EXPIRATION_ALERT = (
    f"{EXPIRATION_ALERT_MARKER} La fecha límite está ausente o no es válida. "
    "Corrige el registro o cancela la reservación; el inventario no fue "
    "liberado automáticamente."
)


class ExpirationOutcome(str, Enum):
    NOT_DUE = "not_due"
    EXPIRED = "expired"
    INVALID = "invalid"


class ReservationError(Exception):
    """Error de negocio con mensaje presentable a la clienta."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.code = code


class InvalidReservationExpiration(ReservationError):
    """An active reservation cannot be evaluated without a valid deadline."""

    def __init__(self) -> None:
        super().__init__(
            "Esta reservación requiere revisión de la tienda antes de mostrar datos de pago.",
            code="invalid_expiration",
        )


# --------------------------------------------------------------------------- #
# Utilidades básicas
# --------------------------------------------------------------------------- #
def now_mx() -> datetime:
    """Fecha y hora actual en el horario de Ciudad de México."""
    return utc_now().astimezone(MX_TZ)


def today_mx() -> date:
    return now_mx().date()


def build_folio(moment: datetime) -> str:
    suffix = "".join(secrets.choice(FOLIO_ALPHABET) for _ in range(4))
    return f"AP-{moment.strftime('%Y%m%d')}-{suffix}"


def money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def available_units(variant: Product_variants) -> int:
    return max(0, int(variant.stock or 0) - int(variant.reserved_stock or 0))


def availability_label(units: int) -> str:
    if units <= 0:
        return "Agotado"
    if units <= 3:
        return "Últimas piezas"
    return "Disponible"


def variant_label(variant: Product_variants) -> str:
    if variant.option_name:
        return f"{variant.option_name}: {variant.option_value}"
    return variant.option_value or ""


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not isinstance(value, str) or CANONICAL_EXPIRATION_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return as_utc(parsed)


def parse_hhmm(value: Optional[str]) -> Optional[Tuple[int, int]]:
    if not value or ":" not in value:
        return None
    try:
        hour, minute = value.split(":")[:2]
        return int(hour), int(minute)
    except ValueError:
        return None


def slot_expiry(delivery_date: str, slot_end: str, grace_hours: int) -> str:
    """Calcula el vencimiento: fin del horario más las horas de gracia."""
    day = date.fromisoformat(delivery_date)
    parts = parse_hhmm(slot_end) or (23, 59)
    end = datetime(day.year, day.month, day.day, parts[0], parts[1], tzinfo=MX_TZ)
    return (end + timedelta(hours=max(0, grace_hours))).isoformat()


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
async def get_store_settings(db: AsyncSession) -> Optional[Store_settings]:
    result = await db.execute(select(Store_settings).order_by(Store_settings.id).limit(1))
    return result.scalars().first()


async def get_private_settings(db: AsyncSession) -> Optional[Private_settings]:
    result = await db.execute(select(Private_settings).order_by(Private_settings.id).limit(1))
    return result.scalars().first()


def store_settings_public(settings: Optional[Store_settings]) -> Dict[str, Any]:
    if settings is None:
        return {
            "shop_name": "Nébula Beauty MX",
            "tagline": "Cosmética para llevar contigo",
            "logo_url": "",
            "hero_image_url": "",
            "color_bg": "#F6F1E7",
            "color_text": "#1A1714",
            "color_accent": "#B8123F",
            "contact_email": "",
            "contact_whatsapp": "",
            "instagram_url": "",
            "tiktok_url": "",
            "facebook_url": "",
            "how_it_works": "",
            "faq_content": "",
            "privacy_policy": "",
            "reservation_policy": "",
            "delivery_instructions": "",
            "reservation_window_days": DEFAULT_WINDOW_DAYS,
            "grace_period_hours": DEFAULT_GRACE_HOURS,
        }
    return {
        "shop_name": settings.shop_name,
        "tagline": settings.tagline or "",
        "logo_url": settings.logo_url or "",
        "hero_image_url": settings.hero_image_url or "",
        "color_bg": settings.color_bg or "#F6F1E7",
        "color_text": settings.color_text or "#1A1714",
        "color_accent": settings.color_accent or "#B8123F",
        "contact_email": settings.contact_email or "",
        "contact_whatsapp": settings.contact_whatsapp or "",
        "instagram_url": settings.instagram_url or "",
        "tiktok_url": settings.tiktok_url or "",
        "facebook_url": settings.facebook_url or "",
        "how_it_works": settings.how_it_works or "",
        "faq_content": settings.faq_content or "",
        "privacy_policy": settings.privacy_policy or "",
        "reservation_policy": settings.reservation_policy or "",
        "delivery_instructions": settings.delivery_instructions or "",
        "reservation_window_days": int(settings.reservation_window_days or DEFAULT_WINDOW_DAYS),
        # 0 horas es una opción válida: vencer justo al terminar el horario.
        "grace_period_hours": (
            DEFAULT_GRACE_HOURS if settings.grace_period_hours is None else int(settings.grace_period_hours)
        ),
    }


# --------------------------------------------------------------------------- #
# Catálogo
# --------------------------------------------------------------------------- #
async def load_variants_for_products(db: AsyncSession, product_ids: List[int]) -> Dict[int, List[Product_variants]]:
    if not product_ids:
        return {}
    result = await db.execute(
        select(Product_variants)
        .where(Product_variants.product_id.in_(product_ids))
        .order_by(Product_variants.id)
    )
    grouped: Dict[int, List[Product_variants]] = {}
    for variant in result.scalars().all():
        if variant.is_active is False:
            continue
        grouped.setdefault(variant.product_id, []).append(variant)
    return grouped


async def load_images_for_products(db: AsyncSession, product_ids: List[int]) -> Dict[int, List[Product_images]]:
    if not product_ids:
        return {}
    result = await db.execute(
        select(Product_images)
        .where(Product_images.product_id.in_(product_ids))
        .order_by(Product_images.sort_order, Product_images.id)
    )
    grouped: Dict[int, List[Product_images]] = {}
    for image in result.scalars().all():
        grouped.setdefault(image.product_id, []).append(image)
    return grouped


def serialize_product(
    product: Products,
    images: List[Product_images],
    variants: List[Product_variants],
    category_name: str = "",
    category_slug: str = "",
    include_detail: bool = False,
) -> Dict[str, Any]:
    total_available = sum(available_units(v) for v in variants)
    payload: Dict[str, Any] = {
        "name": product.name,
        "slug": product.slug,
        "short_description": product.short_description or "",
        "price": money(product.price),
        "category_name": category_name,
        "category_slug": category_slug,
        "is_featured": bool(product.is_featured),
        "tags": [t.strip() for t in (product.tags or "").split(",") if t.strip()],
        "image_url": images[0].url if images else "",
        "image_alt": (images[0].alt_text if images and images[0].alt_text else product.name),
        "available_units": total_available,
        "availability": availability_label(total_available),
    }
    if include_detail:
        payload.update(
            {
                "full_description": product.full_description or "",
                "ingredients": product.ingredients or "",
                "usage_instructions": product.usage_instructions or "",
                "images": [
                    {"url": i.url, "alt_text": i.alt_text or product.name}
                    for i in images
                ],
                "variants": [
                    {
                        "id": v.id,
                        "option_name": v.option_name or "Presentación",
                        "option_value": v.option_value,
                        "label": variant_label(v),
                        "price": money(money(product.price) + money(v.price_delta)),
                        "available_units": available_units(v),
                        "availability": availability_label(available_units(v)),
                    }
                    for v in variants
                ],
            }
        )
    return payload


# --------------------------------------------------------------------------- #
# Inventario
# --------------------------------------------------------------------------- #
async def log_movement(
    db: AsyncSession,
    *,
    variant: Optional[Product_variants],
    product_id: Optional[int],
    reservation_id: Optional[int],
    movement_type: str,
    quantity: int,
    note: str = "",
    admin_user_id: Optional[str] = None,
) -> None:
    db.add(
        Inventory_movements(
            variant_id=variant.id if variant else None,
            product_id=product_id,
            reservation_id=reservation_id,
            movement_type=movement_type,
            quantity=quantity,
            stock_after=int(variant.stock or 0) if variant else None,
            reserved_after=int(variant.reserved_stock or 0) if variant else None,
            note=note,
            admin_user_id=admin_user_id,
        )
    )


async def record_status_change(
    db: AsyncSession,
    *,
    reservation_id: int,
    from_status: Optional[str],
    to_status: str,
    admin_user_id: Optional[str] = None,
    admin_email: Optional[str] = None,
    note: str = "",
) -> None:
    db.add(
        Reservation_status_history(
            reservation_id=reservation_id,
            from_status=from_status,
            to_status=to_status,
            admin_user_id=admin_user_id,
            admin_email=admin_email,
            note=note,
        )
    )


async def _locked_items_and_variants(
    db: AsyncSession, reservation_id: int
) -> List[Tuple[Reservation_items, Optional[Product_variants]]]:
    items_result = await db.execute(
        select(Reservation_items)
        .where(Reservation_items.reservation_id == reservation_id)
        .order_by(Reservation_items.id)
    )
    items = list(items_result.scalars().all())
    variant_ids = sorted({i.variant_id for i in items if i.variant_id})
    variants: Dict[int, Product_variants] = {}
    if variant_ids:
        locked = await db.execute(
            select(Product_variants)
            .where(Product_variants.id.in_(variant_ids))
            .order_by(Product_variants.id)
            .with_for_update()
        )
        variants = {v.id: v for v in locked.scalars().all()}
    return [(item, variants.get(item.variant_id) if item.variant_id else None) for item in items]


async def release_reservation_stock(
    db: AsyncSession,
    reservation: Reservations,
    *,
    reason: str,
    admin_user_id: Optional[str] = None,
) -> None:
    """Libera las unidades apartadas. Idempotente vía `stock_released`."""
    if reservation.stock_released:
        return
    for item, variant in await _locked_items_and_variants(db, reservation.id):
        if variant is None:
            raise ReservationError(
                "No se puede liberar el inventario: falta una variante asociada al apartado."
            )
        quantity = int(item.quantity or 0)
        current_reserved = int(variant.reserved_stock or 0)
        if quantity <= 0 or current_reserved < quantity:
            raise ReservationError(
                "El inventario reservado es inconsistente; no se aplicó ningún cambio."
            )
        variant.reserved_stock = current_reserved - quantity
        await log_movement(
            db,
            variant=variant,
            product_id=item.product_id,
            reservation_id=reservation.id,
            movement_type="liberacion",
            quantity=quantity,
            note=reason,
            admin_user_id=admin_user_id,
        )
    reservation.stock_released = True


async def consume_reservation_stock(
    db: AsyncSession,
    reservation: Reservations,
    *,
    admin_user_id: Optional[str] = None,
    from_expired: bool = False,
) -> None:
    """Convierte el inventario apartado en salida definitiva. Idempotente.

    Un apartado vencido ya devolvió sus piezas a la venta (`from_expired`): al
    entregarlo se descuentan de las disponibles, no de las apartadas.
    """
    if reservation.stock_released and not from_expired:
        return
    for item, variant in await _locked_items_and_variants(db, reservation.id):
        if variant is None:
            raise ReservationError(
                "No se puede entregar el apartado: falta una variante asociada."
            )
        quantity = int(item.quantity or 0)
        current_reserved = int(variant.reserved_stock or 0)
        current_stock = int(variant.stock or 0)
        if from_expired:
            if quantity <= 0 or available_units(variant) < quantity:
                raise ReservationError(
                    f"No quedan piezas libres de «{item.product_name}» para registrar esta entrega: "
                    "se volvieron a apartar. Ajusta el inventario y vuelve a intentarlo."
                )
        elif quantity <= 0 or current_reserved < quantity or current_stock < quantity:
            raise ReservationError(
                "El inventario reservado es inconsistente; no se aplicó ningún cambio."
            )
        else:
            variant.reserved_stock = current_reserved - quantity
        variant.stock = current_stock - quantity
        await log_movement(
            db,
            variant=variant,
            product_id=item.product_id,
            reservation_id=reservation.id,
            movement_type="salida",
            quantity=quantity,
            note=f"Entrega del folio {reservation.folio}",
            admin_user_id=admin_user_id,
        )
    reservation.stock_released = True


def _append_expiration_alert(notes: str) -> str:
    if EXPIRATION_ALERT_MARKER in notes:
        return notes
    separator = "\n\n" if notes else ""
    return f"{notes}{separator}{EXPIRATION_ALERT}"


def _flag_invalid_expiration(reservation: Reservations) -> None:
    """Persist one actionable CRM alert without changing stock or status.

    Only the first detection marks the reservation unread, so an administrator
    can mark it read without the next sweep flipping it back.
    """

    notes = reservation.internal_notes or ""
    if EXPIRATION_ALERT_MARKER in notes:
        return
    reservation.internal_notes = _append_expiration_alert(notes)
    reservation.is_unread = True
    logger.error(
        "Reservación activa %s tiene expires_at ausente o inválido; requiere revisión operativa",
        reservation.id,
    )


async def expire_reservation_if_due(
    db: AsyncSession,
    reservation: Reservations,
    *,
    moment: Optional[datetime] = None,
) -> ExpirationOutcome:
    """Expire one locked reservation and release its stock exactly once."""

    if reservation.status not in ACTIVE_STATUSES:
        return ExpirationOutcome.NOT_DUE
    current = as_utc(moment or utc_now())
    deadline = parse_iso(reservation.expires_at)
    if deadline is None:
        _flag_invalid_expiration(reservation)
        return ExpirationOutcome.INVALID
    if deadline > current:
        return ExpirationOutcome.NOT_DUE

    previous = reservation.status
    reservation.status = STATUS_EXPIRED
    reservation.cancelled_at = current.isoformat()
    reservation.cancel_reason = "Vencida automáticamente por falta de entrega"
    await release_reservation_stock(db, reservation, reason="Vencimiento automático")
    await record_status_change(
        db,
        reservation_id=reservation.id,
        from_status=previous,
        to_status=STATUS_EXPIRED,
        note="Vencimiento automático por periodo de gracia agotado",
    )
    return ExpirationOutcome.EXPIRED


async def _expire_due_reservations_locked(db: AsyncSession) -> List[Reservations]:
    moment = utc_now()
    result = await db.execute(
        select(Reservations)
        .where(Reservations.status.in_(ACTIVE_STATUSES))
        .order_by(Reservations.id)
        .with_for_update(skip_locked=True)
    )
    reservations = list(result.scalars().all())
    due_ids = [
        r.id for r in reservations
        if (deadline := parse_iso(r.expires_at)) is not None and deadline <= moment
    ]
    if due_ids:
        # Lock every affected variant up front in id order, like reservation creation.
        # Locking them one reservation at a time can deadlock with a concurrent order.
        due_variant_ids = select(Reservation_items.variant_id).where(
            Reservation_items.reservation_id.in_(due_ids)
        )
        await db.execute(
            select(Product_variants.id)
            .where(Product_variants.id.in_(due_variant_ids))
            .order_by(Product_variants.id)
            .with_for_update()
        )
    expired: List[Reservations] = []
    for reservation in reservations:
        outcome = await expire_reservation_if_due(db, reservation, moment=moment)
        if outcome is ExpirationOutcome.EXPIRED:
            expired.append(reservation)
    # Already-flagged invalid records change nothing, so page views stay read-only.
    if db.new or db.dirty:
        await db.commit()
    return expired


async def expire_due_reservations(db: AsyncSession) -> List[Reservations]:
    """Vence una sola vez y bloquea cada reservación antes de liberar stock."""
    bind = db.get_bind()
    if bind.dialect.name == "sqlite":
        async with SQLITE_RESERVATION_LOCK:
            return await _expire_due_reservations_locked(db)
    return await _expire_due_reservations_locked(db)


# --------------------------------------------------------------------------- #
# Puntos de entrega y horarios
# --------------------------------------------------------------------------- #
async def load_delivery_options(db: AsyncSession, window_days: int) -> List[Dict[str, Any]]:
    points_result = await db.execute(
        select(Delivery_points).order_by(Delivery_points.sort_order, Delivery_points.id)
    )
    points = [p for p in points_result.scalars().all() if p.is_active is not False]
    if not points:
        return []

    slots_result = await db.execute(
        select(Delivery_slots)
        .where(Delivery_slots.delivery_point_id.in_([p.id for p in points]))
        .order_by(Delivery_slots.weekday, Delivery_slots.start_time)
    )
    slots_by_point: Dict[int, List[Delivery_slots]] = {}
    for slot in slots_result.scalars().all():
        if slot.is_active is False:
            continue
        slots_by_point.setdefault(slot.delivery_point_id, []).append(slot)

    # Conteo de reservaciones activas por punto/fecha/horario para respetar capacidad.
    usage_result = await db.execute(
        select(
            Reservations.delivery_point_id,
            Reservations.delivery_date,
            Reservations.slot_start,
            func.count(Reservations.id),
        )
        .where(Reservations.status.in_(ACTIVE_STATUSES))
        .group_by(Reservations.delivery_point_id, Reservations.delivery_date, Reservations.slot_start)
    )
    usage = {(row[0], row[1], row[2]): int(row[3]) for row in usage_result.all()}

    local_now = now_mx()
    start_day = local_now.date()
    options: List[Dict[str, Any]] = []
    for point in points:
        days: List[Dict[str, Any]] = []
        for offset in range(max(1, window_days)):
            current = start_day + timedelta(days=offset)
            day_slots = []
            for slot in slots_by_point.get(point.id, []):
                if int(slot.weekday) != current.weekday():
                    continue
                start_parts = parse_hhmm(slot.start_time)
                if current == start_day and start_parts is not None:
                    start_moment = datetime(
                        current.year,
                        current.month,
                        current.day,
                        start_parts[0],
                        start_parts[1],
                        tzinfo=MX_TZ,
                    )
                    if start_moment <= local_now:
                        continue
                capacity = int(slot.capacity or 0)
                used = usage.get((point.id, current.isoformat(), slot.start_time), 0)
                if capacity > 0 and used >= capacity:
                    continue
                day_slots.append(
                    {
                        "id": slot.id,
                        "start_time": slot.start_time,
                        "end_time": slot.end_time,
                        "label": f"{slot.start_time} a {slot.end_time}",
                        "capacity": capacity,
                        "remaining": (capacity - used) if capacity > 0 else None,
                    }
                )
            if day_slots:
                days.append(
                    {
                        "date": current.isoformat(),
                        "weekday_label": WEEKDAY_LABELS[current.weekday()],
                        "slots": day_slots,
                    }
                )
        options.append(
            {
                "id": point.id,
                "name": point.name,
                "kind": point.kind or "",
                "address": point.address or "",
                "city": point.city or "",
                "reference": point.reference or "",
                "notes": point.notes or "",
                "days": days,
            }
        )
    return options


# --------------------------------------------------------------------------- #
# Validación de datos de la clienta
# --------------------------------------------------------------------------- #
def sanitize_text(value: Any, max_length: int = 400) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text[:max_length]


def update_internal_notes_preserving_alert(
    reservation: Reservations,
    value: Any,
) -> str:
    """Keep the system expiration alert outside the administrator text limit."""

    preserve_alert = EXPIRATION_ALERT_MARKER in (reservation.internal_notes or "")
    submitted = str(value or "")
    if preserve_alert:
        submitted = submitted.replace(EXPIRATION_ALERT, "")
    admin_notes = sanitize_text(submitted, MAX_ADMIN_INTERNAL_NOTES)
    reservation.internal_notes = (
        _append_expiration_alert(admin_notes) if preserve_alert else admin_notes
    )
    return reservation.internal_notes


def validate_contact(payload: Dict[str, Any]) -> Dict[str, str]:
    full_name = sanitize_text(payload.get("full_name"), 120)
    if len(full_name) < 3:
        raise ReservationError("Escribe tu nombre completo.")

    whatsapp_digits = re.sub(r"\D", "", str(payload.get("whatsapp") or ""))
    if len(whatsapp_digits) != 10:
        raise ReservationError("El WhatsApp debe tener exactamente 10 dígitos.")

    email = sanitize_text(payload.get("email"), 160).lower()
    if not EMAIL_RE.match(email):
        raise ReservationError("Escribe un correo electrónico válido.")

    if not bool(payload.get("privacy_accepted")):
        raise ReservationError("Debes aceptar el aviso de privacidad para continuar.")

    return {
        "full_name": full_name,
        "whatsapp": whatsapp_digits,
        "email": email,
        "notes": sanitize_text(payload.get("notes"), 400),
    }


async def _validate_slot(
    db: AsyncSession, point_id: int, delivery_date: str, slot_start: str, window_days: int
) -> Tuple[Delivery_points, Delivery_slots]:
    point = (
        await db.execute(select(Delivery_points).where(Delivery_points.id == point_id))
    ).scalars().first()
    if point is None or point.is_active is False:
        raise ReservationError("El punto de entrega seleccionado ya no está disponible.")

    try:
        day = date.fromisoformat(delivery_date)
    except (TypeError, ValueError):
        raise ReservationError("Selecciona una fecha de entrega válida.")
    # fromisoformat también acepta "2026-W42-2"; el cupo y los filtros comparan el texto AAAA-MM-DD.
    if day.isoformat() != delivery_date:
        raise ReservationError("Selecciona una fecha de entrega válida.")

    start_day = today_mx()
    if day < start_day or day > start_day + timedelta(days=max(1, window_days) - 1):
        raise ReservationError(
            f"Solo puedes apartar dentro de los próximos {max(1, window_days)} días."
        )

    slot_result = await db.execute(
        select(Delivery_slots).where(
            Delivery_slots.delivery_point_id == point_id,
            Delivery_slots.start_time == slot_start,
            Delivery_slots.weekday == day.weekday(),
        ).with_for_update()
    )
    slot = slot_result.scalars().first()
    if slot is None or slot.is_active is False:
        raise ReservationError("El horario seleccionado ya no está disponible para esa fecha.")
    # Misma regla que load_delivery_options: hoy sólo se aceptan horarios que no han empezado.
    start_parts = parse_hhmm(slot.start_time)
    if day == start_day and start_parts is not None:
        start_moment = datetime(day.year, day.month, day.day, start_parts[0], start_parts[1], tzinfo=MX_TZ)
        if start_moment <= now_mx():
            raise ReservationError("Ese horario ya comenzó. Elige otro horario disponible.")

    capacity = int(slot.capacity or 0)
    if capacity > 0:
        used_result = await db.execute(
            select(func.count(Reservations.id)).where(
                Reservations.delivery_point_id == point_id,
                Reservations.delivery_date == delivery_date,
                Reservations.slot_start == slot_start,
                Reservations.status.in_(ACTIVE_STATUSES),
            )
        )
        if int(used_result.scalar() or 0) >= capacity:
            raise ReservationError("Ese horario acaba de llenarse. Elige otro horario disponible.")

    return point, slot


async def _unique_folio(db: AsyncSession, moment: datetime) -> str:
    for _ in range(12):
        folio = build_folio(moment)
        exists = await db.execute(select(Reservations.id).where(Reservations.folio == folio).limit(1))
        if exists.scalars().first() is None:
            return folio
    return f"AP-{moment.strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"


async def _guard_duplicate(db: AsyncSession, email: str) -> None:
    """Evita reenvíos accidentales usando datos persistidos, no el fingerprint."""
    threshold = utc_now() - timedelta(seconds=90)
    result = await db.execute(
        select(Reservations)
        .where(Reservations.customer_email == email, Reservations.status.in_(ACTIVE_STATUSES))
        .order_by(Reservations.id.desc())
        .limit(1)
    )
    latest = result.scalars().first()
    if latest is None or latest.created_at is None:
        return
    created = as_utc(latest.created_at)
    if created > threshold:
        raise ReservationError(
            "Ya recibimos una solicitud tuya hace unos segundos. Revisa tu correo antes de enviar otra.",
            code="duplicate",
        )


async def check_cart_availability(db: AsyncSession, lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Revalida precios y disponibilidad sin apartar inventario."""
    lines = lines or []
    variant_ids = {int(line.get("variant_id") or 0) for line in lines}
    variants: Dict[int, Product_variants] = {}
    products: Dict[int, Products] = {}
    if variant_ids:
        variants_result = await db.execute(
            select(Product_variants).where(Product_variants.id.in_(variant_ids))
        )
        variants = {v.id: v for v in variants_result.scalars().all()}
    if variants:
        products_result = await db.execute(
            select(Products).where(Products.id.in_({v.product_id for v in variants.values()}))
        )
        products = {p.id: p for p in products_result.scalars().all()}

    results: List[Dict[str, Any]] = []
    for line in lines:
        variant_id = int(line.get("variant_id") or 0)
        quantity = max(1, int(line.get("quantity") or 1))
        variant = variants.get(variant_id)
        if variant is None or variant.is_active is False:
            results.append({"variant_id": variant_id, "ok": False, "reason": "Ya no está disponible"})
            continue
        product = products.get(variant.product_id)
        if product is None or product.is_active is False or product.is_archived:
            results.append({"variant_id": variant_id, "ok": False, "reason": "Ya no está disponible"})
            continue
        units = available_units(variant)
        results.append(
            {
                "variant_id": variant_id,
                "ok": units >= quantity,
                "available_units": units,
                "unit_price": money(money(product.price) + money(variant.price_delta)),
                "product_name": product.name,
                "variant_label": variant_label(variant),
                "reason": "" if units >= quantity else f"Solo quedan {units} piezas",
            }
        )
    return {"lines": results, "all_ok": all(r.get("ok") for r in results) if results else False}


# --------------------------------------------------------------------------- #
# Creación de la reservación
# --------------------------------------------------------------------------- #
async def _create_reservation_locked(db: AsyncSession, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Crea la reservación de forma transaccional y aparta el inventario."""
    settings = await get_store_settings(db)
    config = store_settings_public(settings)
    contact = validate_contact(payload)

    raw_lines = payload.get("items") or []
    if not raw_lines:
        raise ReservationError("Tu apartado está vacío.")
    if len(raw_lines) > MAX_RESERVATION_LINES:
        raise ReservationError("Tu apartado tiene demasiados artículos distintos.")

    await _guard_duplicate(db, contact["email"])

    point, slot = await _validate_slot(
        db,
        int(payload.get("delivery_point_id") or 0),
        sanitize_text(payload.get("delivery_date"), 12),
        sanitize_text(payload.get("slot_start"), 8),
        config["reservation_window_days"],
    )

    # Consolida cantidades por variante y bloquea las filas en orden estable.
    wanted: Dict[int, int] = {}
    for line in raw_lines:
        variant_id = int(line.get("variant_id") or 0)
        quantity = int(line.get("quantity") or 0)
        if variant_id <= 0 or quantity <= 0:
            raise ReservationError("Hay un artículo inválido en tu apartado.")
        wanted[variant_id] = wanted.get(variant_id, 0) + quantity
        if wanted[variant_id] > MAX_RESERVATION_UNITS_PER_LINE:
            raise ReservationError(
                f"La cantidad máxima por artículo es de {MAX_RESERVATION_UNITS_PER_LINE} piezas."
            )
    if sum(wanted.values()) > MAX_RESERVATION_TOTAL_UNITS:
        raise ReservationError(
            f"El apartado no puede superar {MAX_RESERVATION_TOTAL_UNITS} unidades."
        )

    locked = await db.execute(
        select(Product_variants)
        .where(Product_variants.id.in_(sorted(wanted.keys())))
        .order_by(Product_variants.id)
        .with_for_update()
    )
    variants = {v.id: v for v in locked.scalars().all()}
    if len(variants) != len(wanted):
        raise ReservationError("Uno de los productos de tu apartado ya no está disponible.")

    products_result = await db.execute(
        select(Products).where(Products.id.in_({v.product_id for v in variants.values()}))
    )
    products = {p.id: p for p in products_result.scalars().all()}
    images = await load_images_for_products(db, list(products.keys()))

    prepared: List[Dict[str, Any]] = []
    total = 0.0
    for variant_id, quantity in wanted.items():
        variant = variants[variant_id]
        product = products.get(variant.product_id)
        if variant.is_active is False or product is None or product.is_active is False or product.is_archived:
            raise ReservationError(f"«{product.name if product else 'Un producto'}» ya no está disponible.")
        units = available_units(variant)
        if units <= 0:
            raise ReservationError(f"«{product.name}» se agotó mientras armabas tu apartado.")
        if quantity > units:
            raise ReservationError(
                f"De «{product.name} — {variant_label(variant)}» solo quedan {units} piezas."
            )
        unit_price = money(money(product.price) + money(variant.price_delta))
        line_total = money(unit_price * quantity)
        total += line_total
        product_images = images.get(product.id, [])
        prepared.append(
            {
                "variant": variant,
                "product": product,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
                "image_url": product_images[0].url if product_images else "",
            }
        )

    moment = now_mx()
    folio = await _unique_folio(db, moment)

    customer = (
        await db.execute(select(Customers).where(Customers.email == contact["email"]))
    ).scalars().first()
    if customer is None:
        customer = Customers(
            full_name=contact["full_name"],
            whatsapp=contact["whatsapp"],
            email=contact["email"],
            reservation_count=1,
            delivered_count=0,
        )
        db.add(customer)
    else:
        customer.full_name = contact["full_name"]
        customer.whatsapp = contact["whatsapp"]
        customer.reservation_count = int(customer.reservation_count or 0) + 1
    await db.flush()

    # Token de capacidad de 256 bits; su valor crudo nunca se persiste.
    raw_private_token = new_secret_token()
    reservation = Reservations(
        folio=folio,
        private_token_hash=private_token_hash(raw_private_token),
        token_revoked=False,
        customer_id=customer.id,
        customer_name=contact["full_name"],
        customer_whatsapp=contact["whatsapp"],
        customer_email=contact["email"],
        delivery_point_id=point.id,
        delivery_point_name=point.name,
        delivery_point_reference=point.reference or point.address or "",
        delivery_date=sanitize_text(payload.get("delivery_date"), 12),
        slot_start=slot.start_time,
        slot_end=slot.end_time,
        status=STATUS_RECEIVED,
        total_amount=money(total),
        item_count=sum(p["quantity"] for p in prepared),
        customer_notes=contact["notes"],
        internal_notes="",
        is_unread=True,
        privacy_accepted=True,
        expires_at=slot_expiry(
            sanitize_text(payload.get("delivery_date"), 12),
            slot.end_time,
            config["grace_period_hours"],
        ),
        stock_released=False,
        client_fingerprint=sanitize_text(payload.get("fingerprint"), 80),
    )
    db.add(reservation)
    await db.flush()

    for entry in prepared:
        variant: Product_variants = entry["variant"]
        product: Products = entry["product"]
        db.add(
            Reservation_items(
                reservation_id=reservation.id,
                product_id=product.id,
                variant_id=variant.id,
                product_name=product.name,
                product_slug=product.slug,
                variant_label=variant_label(variant),
                unit_price=entry["unit_price"],
                quantity=entry["quantity"],
                line_total=entry["line_total"],
                image_url=entry["image_url"],
            )
        )
        variant.reserved_stock = int(variant.reserved_stock or 0) + entry["quantity"]
        await log_movement(
            db,
            variant=variant,
            product_id=product.id,
            reservation_id=reservation.id,
            movement_type="reserva",
            quantity=entry["quantity"],
            note=f"Apartado del folio {folio}",
        )

    await record_status_change(
        db,
        reservation_id=reservation.id,
        from_status=None,
        to_status=STATUS_RECEIVED,
        note="Solicitud de apartado recibida desde el sitio",
    )

    await db.commit()
    logger.info("Reservación %s creada con %s artículos", folio, reservation.item_count)
    return {
        "id": reservation.id,
        "folio": reservation.folio,
        "private_token": raw_private_token,
        "total_amount": money(reservation.total_amount),
    }


async def create_reservation(db: AsyncSession, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize local SQLite writers; PostgreSQL relies on real row locks.

    The process lock makes local integration tests deterministic but does not
    provide cross-process guarantees. Production configuration rejects SQLite.
    """
    bind = db.get_bind()
    if bind.dialect.name == "sqlite":
        async with SQLITE_RESERVATION_LOCK:
            return await _create_reservation_locked(db, payload)
    return await _create_reservation_locked(db, payload)


# --------------------------------------------------------------------------- #
# Serialización de reservaciones
# --------------------------------------------------------------------------- #
async def load_reservation_items(db: AsyncSession, reservation_id: int) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(Reservation_items)
        .where(Reservation_items.reservation_id == reservation_id)
        .order_by(Reservation_items.id)
    )
    return [
        {
            "id": item.id,
            "product_name": item.product_name,
            "product_slug": item.product_slug or "",
            "variant_label": item.variant_label or "",
            "unit_price": money(item.unit_price),
            "quantity": int(item.quantity or 0),
            "line_total": money(item.line_total),
            "image_url": item.image_url or "",
        }
        for item in result.scalars().all()
    ]


def serialize_reservation(reservation: Reservations, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": reservation.id,
        "folio": reservation.folio,
        "status": reservation.status,
        "status_label": STATUS_LABELS.get(reservation.status, reservation.status),
        "customer_name": reservation.customer_name or "",
        "customer_whatsapp": reservation.customer_whatsapp or "",
        "customer_email": reservation.customer_email or "",
        "delivery_point_name": reservation.delivery_point_name or "",
        "delivery_point_reference": reservation.delivery_point_reference or "",
        "delivery_date": reservation.delivery_date or "",
        "slot_start": reservation.slot_start or "",
        "slot_end": reservation.slot_end or "",
        "total_amount": money(reservation.total_amount),
        "item_count": int(reservation.item_count or 0),
        "customer_notes": reservation.customer_notes or "",
        "internal_notes": reservation.internal_notes or "",
        "is_unread": bool(reservation.is_unread),
        "expires_at": reservation.expires_at or "",
        "cancel_reason": reservation.cancel_reason or "",
        "created_at": reservation.created_at.isoformat() if reservation.created_at else None,
        "items": items,
    }


async def get_reservation_by_token(
    db: AsyncSession,
    token: str,
    *,
    for_update: bool = False,
) -> Optional[Reservations]:
    clean = (token or "").strip()
    if len(clean) < 40 or len(clean) > 128 or re.fullmatch(r"[A-Za-z0-9_-]+", clean) is None:
        return None
    statement = select(Reservations).where(
        Reservations.private_token_hash == private_token_hash(clean)
    ).limit(1)
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    reservation = result.scalars().first()
    if reservation is None or reservation.token_revoked:
        return None
    return reservation


async def _get_confirmation_reservation_locked(
    db: AsyncSession, token: str
) -> Optional[Reservations]:
    reservation = await get_reservation_by_token(db, token, for_update=True)
    if reservation is None:
        return None
    outcome = await expire_reservation_if_due(db, reservation)
    if outcome in {ExpirationOutcome.EXPIRED, ExpirationOutcome.INVALID}:
        await db.commit()
        await db.refresh(reservation)
    if outcome is ExpirationOutcome.INVALID:
        raise InvalidReservationExpiration()
    return reservation


async def get_confirmation_reservation(
    db: AsyncSession, token: str
) -> Optional[Reservations]:
    """Lock and refresh the single reservation addressed by a private token."""

    bind = db.get_bind()
    if bind.dialect.name == "sqlite":
        async with SQLITE_RESERVATION_LOCK:
            return await _get_confirmation_reservation_locked(db, token)
    return await _get_confirmation_reservation_locked(db, token)


# --------------------------------------------------------------------------- #
# Transiciones de estado desde el CRM
# --------------------------------------------------------------------------- #
async def apply_status_change(
    db: AsyncSession,
    reservation: Reservations,
    new_status: str,
    *,
    admin_user_id: str,
    admin_email: str,
    note: str = "",
) -> Reservations:
    if new_status not in ALL_STATUSES:
        raise ReservationError("Estado no válido.")
    locked = await db.execute(
        select(Reservations).where(Reservations.id == reservation.id).with_for_update()
    )
    reservation = locked.scalars().first()
    if reservation is None:
        raise ReservationError("La reservación ya no existe.")
    previous = reservation.status
    if previous == new_status:
        return reservation
    if new_status not in ALLOWED_TRANSITIONS.get(previous, set()):
        raise ReservationError(
            f"No se puede cambiar una reservación de {STATUS_LABELS.get(previous, previous)} "
            f"a {STATUS_LABELS.get(new_status, new_status)}."
        )

    moment = now_mx()
    reservation.status = new_status

    if new_status == STATUS_DELIVERED:
        await consume_reservation_stock(
            db, reservation, admin_user_id=admin_user_id, from_expired=previous == STATUS_EXPIRED
        )
        reservation.delivered_at = moment.isoformat()
        reservation.cancelled_at = None
        reservation.cancel_reason = None
        if reservation.customer_id:
            customer = (
                await db.execute(select(Customers).where(Customers.id == reservation.customer_id))
            ).scalars().first()
            if customer is not None:
                customer.delivered_count = int(customer.delivered_count or 0) + 1
    elif new_status in RELEASING_STATUSES:
        await release_reservation_stock(
            db, reservation, reason=note or STATUS_LABELS[new_status], admin_user_id=admin_user_id
        )
        reservation.cancelled_at = moment.isoformat()
        reservation.cancel_reason = note or STATUS_LABELS[new_status]

    await record_status_change(
        db,
        reservation_id=reservation.id,
        from_status=previous,
        to_status=new_status,
        admin_user_id=admin_user_id,
        admin_email=admin_email,
        note=note,
    )
    await db.commit()
    return reservation
