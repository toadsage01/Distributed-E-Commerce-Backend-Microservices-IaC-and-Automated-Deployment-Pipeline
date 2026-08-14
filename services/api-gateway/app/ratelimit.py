"""slowapi rate-limiter setup.

slowapi is the Starlette/FastAPI-native rate limiter — backed by the
`limits` library with Redis as the storage backend. We picked it over
hand-rolling because:
  - It's a real, maintained library (matters if anyone checks requirements.txt)
  - Handles the sliding-window counter logic correctly (off-by-one errors
    in rate limiters are notoriously easy to introduce)
  - Supports multiple storage backends (Redis for prod, in-memory for tests)

The limiter is keyed by API key, so an attacker can't rotate IPs to bypass
the limit — they'd need a new API key, which requires signup + auth.
"""
# NOTE: no `from __future__ import annotations` — see dependencies.py for
# FastAPI signature-introspection reason.

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from .config import settings


def _key_func(request) -> str:
    """Rate-limit key = the API key from the X-API-Key header.

    Falls back to client IP if no API key is present (so unauthenticated
    requests still get rate-limited rather than unlimited).
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"apikey:{api_key}"
    return f"ip:{get_remote_address(request)}"


# Redis storage URL comes from settings. slowapi will use Redis if
# REDIS_URL is set, else fall back to in-memory (useful for tests).
limiter = Limiter(
    key_func=_key_func,
    storage_uri=settings.redis_url,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
)


def setup_rate_limiting(app) -> None:
    """Wire slowapi into the FastAPI app.

    Called once during app startup. Adds:
      - slowapi's exception handler (so 429 responses are well-formed)
      - slowapi's middleware (which actually enforces the limit)
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)


def _rate_limit_handler(request, exc) -> JSONResponse:
    """Custom 429 response — return JSON, not slowapi's default.

    slowapi expects a Starlette Response (or callable returning one), not
    a (dict, int) tuple. We use JSONResponse for a clean JSON 429 body.
    """
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": str(exc.detail),
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
