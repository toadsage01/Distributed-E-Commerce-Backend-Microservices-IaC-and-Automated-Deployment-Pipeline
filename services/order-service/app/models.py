"""SQLAlchemy ORM models for the Order Service."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    DateTime, String, Integer, Numeric, Boolean, Text, ForeignKey, Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from services.shared.database import Base


# Status is a string enum (not a Python enum) to keep migrations simple.
# Transitions are enforced at the application layer in routers/orders.py.
ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_CONFIRMED = "confirmed"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_CANCELLED = "cancelled"
ORDER_STATUS_FULFILLED = "fulfilled"
ORDER_STATUSES = (
    ORDER_STATUS_PENDING,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_FULFILLED,
)


class Order(Base):
    """An order placed by a user.

    `total_amount` is denormalised from line items at order creation time —
    we don't recompute on every read because product prices can change
    after the order is placed (a real prod system would snapshot the
    product details into OrderLine too, which we do via unit_price).
    """
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ORDER_STATUS_PENDING)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status,
            "total_amount": float(self.total_amount),
            "notes": self.notes,
            "items": [line.to_dict() for line in (self.lines or [])],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class OrderLine(Base):
    """A single product line within an order.

    `unit_price` is the product's price AT THE TIME OF ORDER — protecting
    against later price changes. This is the standard order-line pattern.
    """
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    order: Mapped[Order] = relationship(back_populates="lines")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "unit_price": float(self.unit_price),
            "line_total": float(self.unit_price) * self.quantity,
        }
