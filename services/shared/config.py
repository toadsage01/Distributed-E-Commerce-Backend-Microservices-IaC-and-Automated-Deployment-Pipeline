"""Base settings class used by every service.

Centralises the env-var loading so all four services speak the same config
language (same names, same defaults, same validation). A service only needs to
subclass `BaseSettings` and add its own fields — the boilerplate (DB URL,
Redis URL, JWT secret, environment name) is shared.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    """Settings shared by every service.

    Service-specific settings subclass this and add their own fields.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Environment ---------------------------------------------------------
    env: Literal["local", "dev", "staging", "prod"] = "local"
    log_level: str = "INFO"

    # --- Shared infrastructure ----------------------------------------------
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/ecom"
    redis_url: str = "redis://localhost:6379/0"

    # --- JWT (used by user-service to sign, gateway to verify) --------------
    jwt_secret: str = "change-me-in-prod-please-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7


@lru_cache
def get_platform_settings() -> PlatformSettings:
    """Cached accessor — pydantic-settings parsing is not free."""
    return PlatformSettings()
