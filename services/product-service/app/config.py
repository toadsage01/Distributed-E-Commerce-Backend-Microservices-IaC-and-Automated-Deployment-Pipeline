"""Product-service-specific settings."""
from __future__ import annotations

from services.shared.config import PlatformSettings


class Settings(PlatformSettings):
    db_schema: str = "products"
    port: int = 8002


settings = Settings()
