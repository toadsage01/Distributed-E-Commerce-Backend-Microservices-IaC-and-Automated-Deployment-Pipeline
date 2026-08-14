"""The proxy router — forwards every request to the right downstream service.

This is the heart of the gateway. For each request:
  1. Verify API key (delegates to User Service, cached 60s)
  2. Verify JWT (signature + expiry, no DB hit)
  3. Look up downstream service URL from the path
  4. Forward the request via httpx, propagating headers + body
  5. Add X-User-Id header (from the JWT sub claim) for downstream trust

The downstream services trust X-User-Id because they're behind a security
group that only the gateway can hit. If someone bypasses the gateway,
the security group blocks them.
"""
# NOTE: no `from __future__ import annotations` — see dependencies.py for
# the FastAPI signature-introspection reason.
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from ..config import settings
from ..dependencies import get_downstream_url, verify_api_key, verify_jwt

log = logging.getLogger("api-gateway.proxy")
router = APIRouter()


# Headers we strip from the incoming request before forwarding.
# These would either leak client identity (X-User-Id from a forged request)
# or conflict with downstream's expectations.
_HOP_BY_HOP_HEADERS = {
    "host", "x-api-key", "authorization", "x-user-id",
    "content-length", "transfer-encoding", "connection",
    "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "upgrade",
}


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def proxy(
    request: Request,
    api_user_id: int = Depends(verify_api_key),
    jwt_user_id: int = Depends(verify_jwt),
) -> Response:
    """Forward the request to the appropriate downstream service.

    The two dependencies (`verify_api_key` then `verify_jwt`) handle auth
    before this function body runs — if either fails, FastAPI returns 401
    without executing the proxy logic.
    """
    # jwt_user_id is the authoritative user id — the API key just confirms
    # the request is allowed at all. The JWT sub claim is who's making the
    # request.
    user_id = jwt_user_id or api_user_id

    path = "/" + request.path_params["path"]
    downstream_base = get_downstream_url(path)
    target_url = f"{downstream_base}{path}"

    # Preserve query string
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # Read request body (only once — Starlette streams it)
    body = await request.body()

    # Forward headers, stripping hop-by-hop ones + adding X-User-Id
    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    if user_id:
        forwarded_headers["X-User-Id"] = str(user_id)

    method = request.method
    log.info("Proxy %s %s → %s (user_id=%d)", method, path, downstream_base, user_id)

    try:
        async with httpx.AsyncClient(timeout=settings.proxy_timeout_seconds) as client:
            resp = await client.request(
                method,
                target_url,
                content=body,
                headers=forwarded_headers,
                follow_redirects=False,
            )
    except httpx.ConnectError as exc:
        log.error("Downstream %s unreachable: %s", downstream_base, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Downstream service unavailable: {downstream_base}",
        )
    except httpx.ReadTimeout:
        log.error("Downstream %s timed out", downstream_base)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Downstream service timed out",
        )

    # Build response — copy status, headers (minus hop-by-hop), body
    response_headers = {
        k: v for k, v in resp.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=response_headers,
        media_type=resp.headers.get("content-type"),
    )
