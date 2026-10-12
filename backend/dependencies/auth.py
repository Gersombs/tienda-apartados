"""Central, deny-by-default administrative authorization dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import keyed_token_hash, safe_compare
from core.config import settings
from core.database import get_db
from core.time_utils import as_utc, utc_now
from models.admin_accounts import Admin_accounts
from models.admin_sessions import Admin_sessions
from schemas.auth import UserResponse


def _auth_error() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesión administrativa no es válida.")


async def get_current_admin_account(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Admin_accounts:
    raw_token = request.cookies.get(settings.session_cookie_name, "")
    if not raw_token or len(raw_token) > 256:
        raise _auth_error()

    result = await db.execute(
        select(Admin_sessions, Admin_accounts)
        .join(Admin_accounts, Admin_accounts.id == Admin_sessions.admin_id)
        .where(Admin_sessions.token_hash == keyed_token_hash(raw_token))
        .limit(1)
    )
    row = result.first()
    if row is None:
        raise _auth_error()
    session, admin = row
    now = utc_now()
    if session.revoked_at is not None or as_utc(session.expires_at) <= now or admin.is_active is not True:
        raise _auth_error()

    request.state.admin_session = session
    request.state.admin_account = admin
    return admin


async def get_current_user(admin: Admin_accounts = Depends(get_current_admin_account)) -> UserResponse:
    return UserResponse(
        id=admin.auth_user_id,
        email=admin.email,
        name=admin.name,
        role="admin",
        last_login=admin.last_login_at,
    )


async def require_csrf(request: Request) -> None:
    """Require double-submit CSRF validation for every mutable admin request."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    session: Admin_sessions | None = getattr(request.state, "admin_session", None)
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    header_token = request.headers.get("X-CSRF-Token", "")
    if (
        session is None
        or not cookie_token
        or not header_token
        or not safe_compare(cookie_token, header_token)
        or not safe_compare(session.csrf_hash, keyed_token_hash(header_token))
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La validación CSRF falló.")
