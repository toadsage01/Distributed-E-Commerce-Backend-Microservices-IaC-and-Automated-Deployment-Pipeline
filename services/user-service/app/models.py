"""SQLAlchemy ORM models for the User Service.

Tables live in the `users` schema (search_path is set on the engine).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from services.shared.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class APIKey(Base):
    """API keys issued to clients (mobile apps, partner integrations).

    The gateway checks these on every request before doing anything else —
    no API key, no service. The `key_hash` column stores a sha256 of the
    key so a DB leak doesn't immediately expose working credentials.
    """
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def to_public_dict(self) -> dict:
        # NOTE: deliberately does NOT include key_hash
        return {
            "id": self.id,
            "user_id": self.user_id,
            "label": self.label,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
