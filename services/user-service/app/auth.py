"""Password hashing + API key hashing helpers.

Uses passlib's bcrypt implementation. Bcrypt is slow by design — that's the
point. The API key hash uses sha256 because it's a lookup, not a password:
we need O(1) lookup by key, which bcrypt can't give us.
"""
from __future__ import annotations

import hashlib
import secrets

from passlib.context import CryptContext

from .config import settings


_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=settings.bcrypt_rounds,
)


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def generate_api_key() -> tuple[str, str]:
    """Generate a new raw API key + its sha256 hash.

    The raw key is returned to the caller ONCE (at creation time). The hash
    is what we store — a DB leak doesn't expose working keys, and the
    gateway can still verify incoming keys by hashing them and looking up
    the hash.
    """
    raw = "sk_" + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
