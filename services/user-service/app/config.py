"""User-service-specific settings.

Adds the bcrypt hashing rounds and the schema name to the shared settings.
"""
from __future__ import annotations

from services.shared.config import PlatformSettings


class Settings(PlatformSettings):
    # Postgres schema this service owns. Created by Alembic / init SQL.
    db_schema: str = "users"

    # Bcrypt cost factor — 12 is a reasonable default for prod (≈250ms/hash).
    # Trade-off: higher = slower brute force, but slower signup/login.
    bcrypt_rounds: int = 12

    # Service port (each service listens on a different port in docker-compose
    # so they can all run on the same host in dev).
    port: int = 8001


settings = Settings()
