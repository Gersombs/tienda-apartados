"""Correos transaccionales reales vía Resend con bitácora obligatoria.

Nunca se simula un envío: cada intento queda registrado en la tabla
`notifications` con estado `enviado`, `pendiente` o `fallido`, de modo que el CRM
siempre muestra la realidad y permite reenviar manualmente.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings as app_settings
from core.time_utils import utc_now
from models.notifications import Notifications
from models.reservations import Reservations
from services.reservation_engine import (
    get_private_settings,
    get_store_settings,
    load_reservation_items,
    money,
    store_settings_public,
)

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"
DEFAULT_FROM = "Nébula Beauty MX <onboarding@resend.dev>"

TEMPLATE_RECEIVED = "recibida"
TEMPLATE_CANCELLED = "cancelada"
TEMPLATE_EXPIRED = "vencida"
TEMPLATE_BUSINESS_ALERT = "alerta_negocio"
TEMPLATE_PRIVATE_LINK = "enlace_privado"

CUSTOMER_TEMPLATES = {
    TEMPLATE_RECEIVED,
    TEMPLATE_CANCELLED,
    TEMPLATE_EXPIRED,
    TEMPLATE_PRIVATE_LINK,
}

# Estado nuevo -> correo automático a la clienta. Sólo la cancelación avisa: los demás
# estados son control interno y así el plan gratuito de Resend rinde más.
STATUS_TO_TEMPLATE = {
    "cancelada": TEMPLATE_CANCELLED,
}


def _escape(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "<br>")
    )


def _peso(value: Any) -> str:
    return f"${money(value):,.0f}".replace(",", ",")


def normalize_host(host: Optional[str]) -> str:
    clean = (host or "").strip().rstrip("/")
    if not clean:
        return ""
    if not clean.startswith(("http://", "https://")):
        clean = f"https://{clean}"
    return clean


def confirmation_link(host: str, token: str) -> str:
    base = normalize_host(host)
    if not base:
        return f"/confirmacion#t={token}"
    return f"{base}/confirmacion#t={token}"


def crm_link(host: str, reservation_id: int) -> str:
    base = normalize_host(host)
    if not base:
        return f"/admin?reservacion={reservation_id}"
    return f"{base}/admin?reservacion={reservation_id}"


# --------------------------------------------------------------------------- #
# Plantillas HTML
# --------------------------------------------------------------------------- #
def _items_table(items: List[Dict[str, Any]]) -> str:
    rows = "".join(
        f"""<tr>
              <td style="padding:8px 0;border-bottom:1px solid #E7DFD1;">
                <strong>{_escape(item['product_name'])}</strong><br>
                <span style="color:#6B6257;font-size:13px;">{_escape(item['variant_label'])} · {item['quantity']} pza · {_peso(item['unit_price'])} c/u</span>
              </td>
              <td align="right" style="padding:8px 0;border-bottom:1px solid #E7DFD1;white-space:nowrap;">{_peso(item['line_total'])}</td>
            </tr>"""
        for item in items
    )
    return f'<table width="100%" cellpadding="0" cellspacing="0" role="presentation">{rows}</table>'


def _layout(shop_name: str, heading: str, intro: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="es-MX"><body style="margin:0;padding:24px;background:#F6F1E7;font-family:Helvetica,Arial,sans-serif;color:#1A1714;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px;background:#FDFBF6;border:1px solid #E7DFD1;border-radius:14px;padding:28px;">
        <tr><td>
          <p style="margin:0 0 4px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#B8123F;">{_escape(shop_name)}</p>
          <h1 style="margin:0 0 12px;font-size:22px;line-height:1.25;">{_escape(heading)}</h1>
          <p style="margin:0 0 18px;font-size:15px;line-height:1.6;color:#463F37;">{intro}</p>
          {body}
          <p style="margin:24px 0 0;font-size:12px;line-height:1.6;color:#8A8177;">
            Este correo se envió automáticamente por tu solicitud de apartado. No pagues nada en línea:
            la transferencia se realiza al momento de recibir tus productos.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _delivery_block(reservation: Reservations, instructions: str) -> str:
    return f"""<table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin:18px 0;background:#F1EADC;border-radius:10px;">
      <tr><td style="padding:14px 16px;font-size:14px;line-height:1.6;">
        <strong>Punto de entrega</strong><br>{_escape(reservation.delivery_point_name)}<br>
        <span style="color:#6B6257;">{_escape(reservation.delivery_point_reference)}</span><br><br>
        <strong>Fecha y horario</strong><br>{_escape(reservation.delivery_date)} de {_escape(reservation.slot_start)} a {_escape(reservation.slot_end)}
        {f'<br><br><strong>Instrucciones</strong><br><span style="color:#6B6257;">{_escape(instructions)}</span>' if instructions else ''}
      </td></tr>
    </table>"""


def build_customer_email(
    template: str,
    reservation: Reservations,
    items: List[Dict[str, Any]],
    config: Dict[str, Any],
    link: str,
) -> Dict[str, str]:
    shop_name = config["shop_name"]
    folio = reservation.folio
    total_row = f"""<table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-top:12px;">
        <tr>
          <td style="font-size:15px;"><strong>Total a pagar al entregar</strong></td>
          <td align="right" style="font-size:20px;font-weight:bold;color:#B8123F;">{_peso(reservation.total_amount)}</td>
        </tr>
      </table>"""
    link_button = (
        f"""<p style="margin:22px 0 0;">
          <a href="{_escape(link)}" style="display:inline-block;background:#B8123F;color:#FFF5F7;text-decoration:none;padding:13px 22px;border-radius:999px;font-size:15px;font-weight:bold;">Ver mi apartado</a>
        </p>
        <p style="margin:10px 0 0;font-size:12px;color:#8A8177;word-break:break-all;">Enlace privado: {_escape(link)}</p>"""
        if link
        else ""
    )

    if template == TEMPLATE_PRIVATE_LINK:
        subject = f"Nuevo enlace privado para tu apartado {folio}"
        heading = "Tu nuevo enlace privado"
        intro = (
            f"Hola {_escape(reservation.customer_name)}, generamos un nuevo enlace para consultar "
            f"el apartado <strong>{_escape(folio)}</strong>. El enlace anterior ya no funciona."
        )
    elif template == TEMPLATE_RECEIVED:
        subject = f"Recibimos tu solicitud de apartado {folio}"
        heading = "Tu apartado quedó registrado"
        intro = (
            f"Hola {_escape(reservation.customer_name)}, guardamos tus productos con el folio "
            f"<strong>{_escape(folio)}</strong>. Te esperamos en el punto y horario que elegiste; "
            "si ya no puedes asistir, cancélalo desde tu enlace privado."
        )
    elif template == TEMPLATE_EXPIRED:
        subject = f"Tu apartado {folio} venció"
        heading = "Tu apartado venció"
        intro = (
            f"Hola {_escape(reservation.customer_name)}, liberamos los productos del apartado "
            f"<strong>{_escape(folio)}</strong> porque pasó el horario de entrega. Puedes apartar de nuevo cuando quieras."
        )
    else:
        subject = f"Tu apartado {folio} fue cancelado"
        heading = "Cancelamos tu apartado"
        intro = (
            f"Hola {_escape(reservation.customer_name)}, cancelamos el apartado "
            f"<strong>{_escape(folio)}</strong>."
            + (
                f" Motivo: {_escape(reservation.cancel_reason)}."
                if reservation.cancel_reason
                else ""
            )
        )

    if template in (TEMPLATE_CANCELLED, TEMPLATE_EXPIRED):
        body = _items_table(items) + total_row
    else:
        body = (
            _items_table(items)
            + total_row
            + _delivery_block(reservation, config.get("delivery_instructions", ""))
            + link_button
        )

    return {"subject": subject, "html": _layout(shop_name, heading, intro, body)}


def build_business_email(
    reservation: Reservations,
    items: List[Dict[str, Any]],
    config: Dict[str, Any],
    link: str,
) -> Dict[str, str]:
    whatsapp = reservation.customer_whatsapp or ""
    contact = f"""<table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin:18px 0;background:#F1EADC;border-radius:10px;">
      <tr><td style="padding:14px 16px;font-size:14px;line-height:1.7;">
        <strong>Clienta</strong><br>{_escape(reservation.customer_name)}<br>
        WhatsApp: <a href="https://wa.me/52{_escape(whatsapp)}" style="color:#B8123F;">{_escape(whatsapp)}</a><br>
        Correo: {_escape(reservation.customer_email)}<br><br>
        <strong>Entrega</strong><br>{_escape(reservation.delivery_point_name)} — {_escape(reservation.delivery_point_reference)}<br>
        {_escape(reservation.delivery_date)} de {_escape(reservation.slot_start)} a {_escape(reservation.slot_end)}
        {f'<br><br><strong>Notas de la clienta</strong><br>{_escape(reservation.customer_notes)}' if reservation.customer_notes else ''}
      </td></tr>
    </table>"""
    total_row = f"""<table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-top:12px;">
        <tr>
          <td style="font-size:15px;"><strong>Total esperado</strong></td>
          <td align="right" style="font-size:20px;font-weight:bold;color:#B8123F;">{_peso(reservation.total_amount)}</td>
        </tr>
      </table>"""
    button = f"""<p style="margin:22px 0 0;">
        <a href="{_escape(link)}" style="display:inline-block;background:#1A1714;color:#F6F1E7;text-decoration:none;padding:13px 22px;border-radius:999px;font-size:15px;font-weight:bold;">Abrir en el CRM</a>
      </p>"""
    return {
        "subject": f"Nueva reservación {reservation.folio} — {_peso(reservation.total_amount)}",
        "html": _layout(
            config["shop_name"],
            f"Nueva reservación {reservation.folio}",
            "Entró una solicitud de apartado nueva. Revisa el detalle y confírmala desde el CRM.",
            contact + _items_table(items) + total_row + button,
        ),
    }


# --------------------------------------------------------------------------- #
# Envío
# --------------------------------------------------------------------------- #
async def _send_via_resend(
    api_key: str, sender: str, to: List[str], subject: str, html: str, reply_to: str = ""
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"from": sender, "to": to, "subject": subject, "html": html}
    if reply_to:
        body["reply_to"] = reply_to
    # Short timeout: emails are sent inside the customer's request.
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            response = await http.post(
                RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            )
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "unreachable": True,
            "error": f"No se pudo conectar con Resend ({type(exc).__name__}).",
        }
    if response.status_code >= 400:
        return {
            "ok": False,
            "error": f"Resend rechazó la solicitud con HTTP {response.status_code}.",
        }
    try:
        data = response.json()
    except ValueError:
        data = {}
    return {"ok": True, "message_id": str(data.get("id") or "")}


async def _log_notification(
    db: AsyncSession,
    *,
    reservation_id: Optional[int],
    recipient_type: str,
    recipient_email: str,
    template: str,
    subject: str,
    status: str,
    error_message: str = "",
    provider_message_id: str = "",
    existing: Optional[Notifications] = None,
) -> Notifications:
    moment = utc_now().isoformat() if status == "enviado" else None
    if existing is not None:
        existing.status = status
        existing.error_message = error_message
        existing.provider_message_id = provider_message_id
        existing.sent_at = moment
        existing.attempts = int(existing.attempts or 0) + 1
        existing.subject = subject
        return existing
    record = Notifications(
        reservation_id=reservation_id,
        recipient_type=recipient_type,
        recipient_email=recipient_email,
        template=template,
        subject=subject,
        status=status,
        error_message=error_message,
        provider_message_id=provider_message_id,
        sent_at=moment,
        attempts=1,
    )
    db.add(record)
    return record


async def _existing_notification(
    db: AsyncSession, reservation_id: int, template: str, recipient_email: str
) -> Optional[Notifications]:
    result = await db.execute(
        select(Notifications)
        .where(
            Notifications.reservation_id == reservation_id,
            Notifications.template == template,
            Notifications.recipient_email == recipient_email,
        )
        .order_by(Notifications.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def dispatch_reservation_emails(
    db: AsyncSession,
    reservation_id: int,
    templates: List[str],
    *,
    app_host: str = "",
    force: bool = False,
    confirmation_token: str = "",
) -> List[Dict[str, Any]]:
    """Envía las plantillas indicadas y registra el resultado real de cada correo.

    Nunca lanza excepción: si el correo falla, la reservación se conserva y el
    error queda visible en el CRM para reenviarlo manualmente.
    """
    reservation = (
        await db.execute(select(Reservations).where(Reservations.id == reservation_id))
    ).scalars().first()
    if reservation is None:
        return []

    settings = await get_store_settings(db)
    config = store_settings_public(settings)
    private = await get_private_settings(db)
    items = await load_reservation_items(db, reservation.id)

    api_key = app_settings.resend_api_key.strip()
    # El remitente es el dominio verificado del operador (variable de entorno); cada
    # tienda sólo elige el nombre visible, y las respuestas llegan a su correo.
    from_email = app_settings.email_from_address.strip()
    from_name = (
        (private.notification_from_name if private else "")
        or config["shop_name"]
        or app_settings.email_from_name
    ).strip().replace('"', "")
    sender = f'"{from_name}" <{from_email}>' if from_email else DEFAULT_FROM
    reply_to = (config.get("contact_email") or "").strip()

    recipients_raw = (
        (private.alert_recipients if private else "")
        or app_settings.admin_email
        or config.get("contact_email", "")
    )
    business_recipients = [r.strip() for r in str(recipients_raw).replace(";", ",").split(",") if r.strip()]

    # Se materializan los datos necesarios y se cierra la fase de lectura antes
    # de llamar al proveedor externo de correo.
    await db.commit()

    plan: List[Dict[str, Any]] = []
    for template in templates:
        if template == TEMPLATE_BUSINESS_ALERT:
            content = build_business_email(reservation, items, config, crm_link(app_host, reservation.id))
            for recipient in business_recipients:
                plan.append(
                    {
                        "template": template,
                        "recipient_type": "negocio",
                        "recipient_email": recipient,
                        "subject": content["subject"],
                        "html": content["html"],
                    }
                )
        elif template in CUSTOMER_TEMPLATES and reservation.customer_email:
            content = build_customer_email(
                template,
                reservation,
                items,
                config,
                confirmation_link(app_host, confirmation_token) if confirmation_token else "",
            )
            plan.append(
                {
                    "template": template,
                    "recipient_type": "cliente",
                    "recipient_email": reservation.customer_email,
                    "subject": content["subject"],
                    "html": content["html"],
                }
            )

    outcomes: List[Dict[str, Any]] = []
    provider_unreachable = ""
    for entry in plan:
        existing = await _existing_notification(
            db, reservation.id, entry["template"], entry["recipient_email"]
        )
        if existing is not None and existing.status == "enviado" and not force:
            outcomes.append(
                {
                    "template": entry["template"],
                    "recipient_email": entry["recipient_email"],
                    "status": "enviado",
                    "skipped": True,
                }
            )
            continue

        if not api_key:
            status, error, message_id = (
                "pendiente",
                "Falta configurar RESEND_API_KEY en la plataforma para enviar correos.",
                "",
            )
        elif provider_unreachable:
            # No repetir la espera del timeout: la clienta sigue esperando la respuesta.
            status, error, message_id = "fallido", provider_unreachable, ""
        else:
            await db.commit()
            result = await _send_via_resend(
                api_key,
                sender,
                [entry["recipient_email"]],
                entry["subject"],
                entry["html"],
                # La clienta responde a la tienda; la tienda responde a la clienta.
                reply_to=reply_to if entry["recipient_type"] == "cliente" else reservation.customer_email or "",
            )
            if result.get("ok"):
                status, error, message_id = "enviado", "", result.get("message_id", "")
            else:
                status, error, message_id = "fallido", str(result.get("error", ""))[:480], ""
                logger.error("Fallo de correo (%s): %s", entry["template"], error)
                if result.get("unreachable"):
                    provider_unreachable = error

        refreshed = await _existing_notification(
            db, reservation.id, entry["template"], entry["recipient_email"]
        )
        await _log_notification(
            db,
            reservation_id=reservation.id,
            recipient_type=entry["recipient_type"],
            recipient_email=entry["recipient_email"],
            template=entry["template"],
            subject=entry["subject"],
            status=status,
            error_message=error,
            provider_message_id=message_id,
            existing=refreshed,
        )
        await db.commit()
        outcomes.append(
            {
                "template": entry["template"],
                "recipient_email": entry["recipient_email"],
                "status": status,
                "error": error,
            }
        )

    return outcomes


async def notification_log(db: AsyncSession, reservation_id: int) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(Notifications)
        .where(Notifications.reservation_id == reservation_id)
        .order_by(Notifications.id.desc())
    )
    return [
        {
            "id": n.id,
            "recipient_type": n.recipient_type,
            "recipient_email": n.recipient_email or "",
            "template": n.template,
            "subject": n.subject or "",
            "status": n.status,
            "error_message": n.error_message or "",
            "sent_at": n.sent_at or "",
            "attempts": int(n.attempts or 0),
        }
        for n in result.scalars().all()
    ]


def status_template(status: str) -> Optional[str]:
    """Plantilla de correo que corresponde a un nuevo estado, si aplica."""
    return STATUS_TO_TEMPLATE.get(status)
