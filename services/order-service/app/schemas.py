"""Pydantic request/response models for the Order Service."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class OrderLineRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100)


class OrderCreate(BaseModel):
    items: list[OrderLineRequest] = Field(min_length=1, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=2000)


class OrderLineOut(BaseModel):
    id: int
    product_id: int
    product_name: str
    quantity: int
    unit_price: float
    line_total: float

    class Config:
        from_attributes = True


class OrderOut(BaseModel):
    id: int
    user_id: int
    status: str
    total_amount: float
    notes: Optional[str] = None
    items: list[OrderLineOut] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class OrderStatusUpdate(BaseModel):
    status: str = Field(pattern="^(confirmed|paid|cancelled|fulfilled)$")
