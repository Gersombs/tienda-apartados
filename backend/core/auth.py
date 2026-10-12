"""Cryptographic primitives for local administrative authentication."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from email_validator import EmailNotValidError, validate_email as validate_email_address

from core.config import settings


password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)


def normalize_email(email: str) -> str:
    return (email or "").strip().casefold()


def validate_admin_email(email: str) -> str:
    """Validate and normalize admin email identically in HTTP and CLI flows."""

    try:
        validated = validate_email_address((email or "").strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError("Proporciona un correo válido.") from exc
    return normalize_email(validated.normalized)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("La contraseña debe tener al menos 12 caracteres.")
    if len(password) > 1024:
        raise ValueError("La contraseña es demasiado larga.")
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, TypeError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return password_hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, TypeError):
        return True


def new_secret_token() -> str:
    """Return at least 256 bits of URL-safe cryptographic randomness."""
    return secrets.token_urlsafe(32)


def keyed_token_hash(token: str) -> str:
    """Hash session/CSRF tokens without persisting their raw value."""
    return hmac.new(settings.auth_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def private_token_hash(token: str) -> str:
    """Hash confirmation capabilities for indexed database lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def safe_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left or "", right or "")
