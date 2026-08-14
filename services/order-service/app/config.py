"""Order-service-specific settings.

Adds the URLs of the User and Product services — needed because Order
Service calls them over HTTP (that's what makes this genuinely
"microservices" rather than one app split into folders).
"""
from __future__ import annotations

from services.shared.config import PlatformSettings


class Settings(PlatformSettings):
    db_schema: str = "orders"
    port: int = 8003

    # Internal service URLs. In docker-compose these are the service names.
    # In ECS/EKS these would be the internal ALB DNS or service discovery name.
    user_service_url: str = "http://user-service:8001"
    product_service_url: str = "http://product-service:8002"

    # Inter-service call settings. Short timeouts + limited retries so
    # the order flow doesn't hang forever under degraded conditions.
    http_timeout_seconds: float = 3.0
    http_retry_max: int = 2
    http_retry_backoff_seconds: float = 0.2


settings = Settings()
