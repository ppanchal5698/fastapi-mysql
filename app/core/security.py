"""
Password hashing and JWT token creation utilities.

Decoding / validation lives in dependencies.py (FastAPI dependency layer).
This module handles the write side: creating tokens and hashing passwords.
"""

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from ..config import settings


def create_access_token(
    subject: int | str,
    email: str,
    roles: list[str] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject: User ID — stored in the ``sub`` claim.
        email: User email — stored in the ``email`` claim.
        roles: Optional list of role strings.
        expires_delta: Custom TTL. Defaults to 30 minutes.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=30))

    payload: dict[str, object] = {
        "sub": str(subject),
        "email": email,
        "roles": roles or [],
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def hash_password(password: str) -> str:
    """
    Hash a plaintext password using PBKDF2-HMAC-SHA256 with a random 32-byte salt.
    Returns ``salt$hash`` (hex-encoded) for storage.
    """
    salt = os.urandom(32)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations=600_000,
    )
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """
    Verify a plaintext password against a ``salt$hash`` string from :func:`hash_password`.
    Uses constant-time comparison to prevent timing attacks.
    """
    try:
        salt_hex, hash_hex = stored.split("$", maxsplit=1)
    except ValueError:
        return False

    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations=600_000,
    )
    return hmac.compare_digest(dk, expected)
