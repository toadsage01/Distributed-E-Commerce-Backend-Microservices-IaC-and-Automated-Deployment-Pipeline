"""Pydantic request/response models for the Product Service."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, condecimal


class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    stock: int = Field(ge=0, default=0)


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    """Partial update — all fields optional."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    stock: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class ProductOut(BaseModel):
    """Response model — price as float so JSON output is numeric, not string.

    Internally we keep Decimal end-to-end for precision; we only flatten to
    float at the JSON boundary (where two-decimal precision is fine for
    display purposes).
    """
    id: int
    name: str
    description: Optional[str] = None
    price: float
    stock: int
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True
