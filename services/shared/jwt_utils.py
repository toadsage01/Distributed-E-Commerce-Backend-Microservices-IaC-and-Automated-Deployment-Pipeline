"""JWT encode/decode helpers.

User Service uses `encode_access_token` / `encode_refresh_token` to issue
tokens at login. The API Gateway uses `decode_access_token` to verify the
signature on every incoming request — no DB hit required, which is the whole
point of stateless JWT auth in a microservices setup.

Tokens are HS256-signed with a shared secret (`jwt_secret`) configured on
both sides via env var. In a real prod system you'd use RS256 with the
private key held only by User Service and the public key distributed to the
gateway — but HS256 is fine for a single-org deployment and avoids the
key-distribution headache.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from .config import get_platform_settings


def _encode(payload: dict[str, Any], ttl: timedelta) -> str:
    settings = get_platform_settings()
    now = datetime.now(timezone.utc)
    body = {
        **payload,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(body, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def encode_access_token(user_id: str | int, extra_claims: dict[str, Any] | None = None) -> str:
    """Short-lived access token. Verified on every gateway request."""
    settings = get_platform_settings()
    payload = {"sub": str(user_id), "typ": "access", **(extra_claims or {})}
    return _encode(payload, timedelta(minutes=settings.access_token_ttl_minutes))


def encode_refresh_token(user_id: str | int) -> str:
    """Long-lived refresh token. Used to mint new access tokens without
    re-prompting the password. Should be rotated on every use in a real
    system; we keep the rotation simple here for clarity.
    """
    settings = get_platform_settings()
    payload = {"sub": str(user_id), "typ": "refresh"}
    return _encode(payload, timedelta(days=settings.refresh_token_ttl_days))


def decode_token(token: str) -> dict[str, Any]:
    """Verify signature + expiry, return claims.

    Raises `jwt.JWTError` (or a subclass) if anything is wrong — callers
    should catch this and convert to a 401.
    """
    settings = get_platform_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise exc
