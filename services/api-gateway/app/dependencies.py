"""Request auth + routing dependencies.

Two layers of auth at the gateway:
  1. API key check — every non-public request must include X-API-Key
  2. JWT verification — every non-public request must include a valid
     Bearer token (access token from /auth/login or /auth/signup)

After both pass, the gateway sets X-User-Id on the outgoing request to
the downstream service. Internal services trust this header (they're
behind a security group that only the gateway can hit).
"""
# NOTE: deliberately no `from __future__ import annotations` here.
# FastAPI's signature introspection needs the real `Request` class object
# in the annotation, not the string 'Request' that PEP 563 would produce.
# With future annotations, `request: Request` would be stored as the
# string 'Request' and FastAPI would treat `request` as a query param,
# returning 422 on every request.
import logging
from typing import Optional

import httpx
from fastapi import Header, HTTPException, Request, status

from services.shared.jwt_utils import decode_token

from .config import settings

log = logging.getLogger("api-gateway.deps")


# ---------------------------------------------------------------------------
# API key verification (delegates to User Service)
# ---------------------------------------------------------------------------

# Cache API-key lookups for 60s in-memory. Saves a round-trip to User Service
# on every request. Trade-off: revoking an API key takes up to 60s to take
# effect. Acceptable for most use cases; if you need instant revocation,
# use Redis with a TTL.
_api_key_cache: dict[str, tuple[int, float]] = {}  # key_hash -> (user_id, expires_at)
_API_KEY_TTL_SECONDS = 60.0


async def verify_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> int:
    """Verify the X-API-Key header against the User Service.

    Returns the user_id that owns the API key. Raises 401 if missing or
    invalid, 502 if User Service is unreachable.

    Public paths (signup/login/etc.) bypass this — they're listed in
    settings.public_paths and short-circuited by the router.
    """
    import time
    path = request.url.path

    # Public paths don't need an API key
    for public in settings.public_paths:
        if path == public or path.startswith(public.rstrip("/") + "/"):
            return 0  # anonymous

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": 'ApiKey realm="api"'},
        )

    # Check cache
    now = time.time()
    if x_api_key in _api_key_cache:
        user_id, expires = _api_key_cache[x_api_key]
        if now < expires:
            return user_id

    # Cache miss → call User Service
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(
                f"{settings.user_service_url}/auth/api-keys/verify",
                params={"key": x_api_key},
            )
    except httpx.HTTPError as exc:
        log.error("User service unreachable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Auth service unavailable",
        )

    if r.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Auth service error: {r.status_code}",
        )

    user_id = r.json()["user_id"]
    _api_key_cache[x_api_key] = (user_id, now + _API_KEY_TTL_SECONDS)
    return user_id


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------

def verify_jwt(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> int:
    """Verify the Bearer JWT.

    Returns the user_id from the JWT `sub` claim. Raises 401 if missing,
    expired, or malformed.

    Public paths (signup/login/etc.) bypass this — same as API key check.
    """
    path = request.url.path
    for public in settings.public_paths:
        if path == public or path.startswith(public.rstrip("/") + "/"):
            return 0  # anonymous

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": 'Bearer realm="api"'},
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    if claims.get("typ") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong token type — access token required",
        )

    try:
        return int(claims["sub"])
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token",
        )


# ---------------------------------------------------------------------------
# Routing — map URL prefix → downstream service
# ---------------------------------------------------------------------------

def get_downstream_url(path: str) -> str:
    """Map an incoming path to its downstream service URL.

    Routing table:
      /auth/*   → user-service   (signup/login/api-keys + user lookups)
      /users/*  → user-service
      /products/* → product-service
      /orders/*   → order-service

    Returns the full URL (downstream + path + querystring) for proxying.
    """
    if path.startswith("/auth") or path.startswith("/users"):
        return settings.user_service_url
    if path.startswith("/products"):
        return settings.product_service_url
    if path.startswith("/orders"):
        return settings.order_service_url
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No downstream service for path: {path}",
    )
