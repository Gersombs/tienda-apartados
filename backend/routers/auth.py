"""Local administrative login. There is deliberately no registration route."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import (
    hash_password,
    keyed_token_hash,
    new_secret_token,
    normalize_email,
    password_needs_rehash,
    verify_password,
)
from core.config import settings
from core.database import get_db
from core.time_utils import utc_now
from dependencies.auth import get_current_admin_account, get_current_user, require_csrf
from models.admin_accounts import Admin_accounts
from models.admin_sessions import Admin_sessions
from schemas.auth import LoginRequest, LoginResponse, PasswordChangeRequest, UserResponse


router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
logger = logging.getLogger(__name__)
GENERIC_LOGIN_ERROR = "El correo o la contraseña no son válidos."
DUMMY_PASSWORD_HASH = hash_password("not-a-real-admin-password")


class LoginRateLimiter:
    """Process-local limiter; production should also enforce a limit at the edge."""

    def __init__(self, max_attempts: int | None = None, window_seconds: int | None = None) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._max = max_attempts
        self._window = window_seconds

    @property
    def window(self) -> int:
        return self._window or settings.login_window_seconds

    def _trim(self, key: str, now: float) -> deque[float]:
        # .get y no [key]: consultar una IP sin intentos no debe dejarle una entrada vacía para siempre.
        attempts = self._attempts.get(key, deque())
        cutoff = now - self.window
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            self._attempts.pop(key, None)
        return attempts

    def check(self, key: str) -> None:
        now = time.monotonic()
        if len(self._trim(key, now)) >= (self._max or settings.login_max_attempts):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiados intentos. Espera antes de volver a intentar.",
                headers={"Retry-After": str(self.window)},
            )

    def fail(self, key: str) -> None:
        now = time.monotonic()
        self._trim(key, now)
        self._attempts[key].append(now)

    def clear(self, key: str) -> None:
        self._attempts.pop(key, None)

    def reset_for_tests(self) -> None:
        self._attempts.clear()


login_limiter = LoginRateLimiter()


def _rate_keys(request: Request, email: str) -> tuple[str, str]:
    # La última entrada de X-Forwarded-For la escribe el proxy de la plataforma; las anteriores las elige el cliente.
    forwarded = ",".join(request.headers.getlist("x-forwarded-for"))
    peer = forwarded.rsplit(",", 1)[-1].strip() or (request.client.host if request.client else "unknown")
    peer_key = hashlib.sha256(f"ip|{peer}".encode("utf-8")).hexdigest()
    account_key = hashlib.sha256(
        f"account|{peer}|{normalize_email(email)}".encode("utf-8")
    ).hexdigest()
    return peer_key, account_key


def _validate_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in settings.cors_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origen no permitido.")


def _set_session_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    max_age = settings.session_lifetime_minutes * 60
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    _validate_origin(request)
    normalized = normalize_email(str(payload.email))
    rate_keys = _rate_keys(request, normalized)
    for key in rate_keys:
        login_limiter.check(key)

    result = await db.execute(
        select(Admin_accounts).where(Admin_accounts.normalized_email == normalized).limit(1)
    )
    admin = result.scalars().first()
    password_hash = admin.password_hash if admin is not None else DUMMY_PASSWORD_HASH
    valid = verify_password(password_hash, payload.password)
    if admin is None or admin.is_active is not True or not valid:
        for key in rate_keys:
            login_limiter.fail(key)
        logger.warning("Administrative login failed for request fingerprint %s", rate_keys[1][:12])
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_LOGIN_ERROR)

    for key in rate_keys:
        login_limiter.clear(key)
    if password_needs_rehash(admin.password_hash):
        admin.password_hash = hash_password(payload.password)

    now = utc_now()
    session_token = new_secret_token()
    csrf_token = new_secret_token()
    db.add(
        Admin_sessions(
            admin_id=admin.id,
            token_hash=keyed_token_hash(session_token),
            csrf_hash=keyed_token_hash(csrf_token),
            expires_at=now + timedelta(minutes=settings.session_lifetime_minutes),
        )
    )
    admin.last_login_at = now
    await db.commit()
    _set_session_cookies(response, session_token, csrf_token)

    return LoginResponse(
        user=UserResponse(
            id=admin.auth_user_id,
            email=admin.email,
            name=admin.name,
            role="admin",
            last_login=admin.last_login_at,
        )
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    return current_user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    admin: Admin_accounts = Depends(get_current_admin_account),
    _csrf: None = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Mismo límite que el login: una sesión robada no puede adivinar la contraseña actual.
    rate_keys = _rate_keys(request, admin.normalized_email)
    for key in rate_keys:
        login_limiter.check(key)
    if not verify_password(admin.password_hash, payload.current_password):
        for key in rate_keys:
            login_limiter.fail(key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña actual no es correcta.")

    admin.password_hash = hash_password(payload.new_password)
    # Cierra los demás dispositivos (por ejemplo, un celular perdido); éste sigue dentro.
    current: Admin_sessions = request.state.admin_session
    await db.execute(
        delete(Admin_sessions).where(Admin_sessions.admin_id == admin.id, Admin_sessions.id != current.id)
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    _admin: Admin_accounts = Depends(get_current_admin_account),
    _csrf: None = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Response:
    session: Admin_sessions = request.state.admin_session
    session.revoked_at = utc_now()
    await db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/", secure=settings.cookie_secure, samesite="lax")
    response.delete_cookie(settings.csrf_cookie_name, path="/", secure=settings.cookie_secure, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response
