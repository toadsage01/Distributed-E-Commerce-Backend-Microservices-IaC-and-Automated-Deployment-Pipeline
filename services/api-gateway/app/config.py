"""API Gateway settings.

Adds:
  - The downstream service URLs (where to route to)
  - The rate-limit quota (100 req/min per API key — industry standard
    for public APIs without bursting)
  - The Redis URL (where slowapi stores the rate-limit counters)
  - The list of public paths that bypass auth (e.g. /auth/login, /health)
"""
from __future__ import annotations

from services.shared.config import PlatformSettings


class Settings(PlatformSettings):
    port: int = 8000

    # Downstream service URLs. In docker-compose these are service names;
    # in prod these are internal ALB DNS names (private subnet only).
    user_service_url: str = "http://user-service:8001"
    product_service_url: str = "http://product-service:8002"
    order_service_url: str = "http://order-service:8003"

    # Rate limiting — 100 req/min per API key. This is enforced at the
    # gateway only, NOT at the downstream services (they trust the
    # gateway, which is the standard pattern).
    rate_limit_per_minute: int = 100

    # Proxy timeout — slightly longer than the downstream's own timeout
    # so the gateway doesn't give up before the downstream does.
    proxy_timeout_seconds: float = 5.0

    # Public paths that bypass both API-key check AND JWT verification.
    # Used for signup/login/health/docs.
    public_paths: tuple[str, ...] = (
        "/auth/signup",
        "/auth/login",
        "/auth/refresh",
        "/auth/api-keys",  # NOTE: POST is public (issues key), GET needs auth
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    )


settings = Settings()
