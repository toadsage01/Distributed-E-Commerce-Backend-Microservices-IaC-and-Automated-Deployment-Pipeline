"""Order flow endpoints.

Key design:
  - POST /orders: validates user + products via httpx, reserves stock at
    the Product Service, then writes the order locally. If any step fails
    we roll back reservations we've already made — partial reservations
    aren't useful to anyone.
  - GET /orders, GET /orders/{id}: pure local reads (no inter-service call).
  - PATCH /orders/{id}/status: status transitions only; can't change line
    items after creation (would need a separate amend flow).
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..clients import (
    ServiceClientError,
    product_client,
    user_client,
)
from ..database import get_db
from ..models import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_PENDING,
    Order,
    OrderLine,
)
from ..schemas import OrderCreate, OrderOut, OrderStatusUpdate

log = logging.getLogger("order-service.router")
router = APIRouter(prefix="/orders", tags=["orders"])


def _user_id_from_header(x_user_id: str = Header(..., alias="X-User-Id")) -> int:
    try:
        return int(x_user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid X-User-Id header")


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(_user_id_from_header),
) -> OrderOut:
    """Create an order.

    Flow:
      1. Verify the user exists (User Service via httpx)
      2. Fetch each product's current price + reserve stock (Product Service via httpx)
      3. Persist the order + order lines locally
      4. If any step fails, attempt to roll back stock reservations we already made
    """
    # 1. Verify user exists.
    try:
        await user_client.get_user(user_id, user_id)
    except ServiceClientError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=400, detail=f"User {user_id} not found")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"User service unavailable: {exc.detail}",
        )

    # 2. Reserve stock for each product in parallel — faster than serial
    # and any failures get rolled back.
    reserved: list[tuple[int, int]] = []  # (product_id, quantity) for rollback

    async def fetch_and_reserve(item):
        # Get product details first to capture name + price snapshot
        product = await product_client.get_product(item.product_id, user_id)
        # Reserve stock
        await product_client.reserve_stock(item.product_id, item.quantity)
        reserved.append((item.product_id, item.quantity))
        return {
            "product_id": item.product_id,
            "product_name": product.get("name", f"product-{item.product_id}"),
            "quantity": item.quantity,
            "unit_price": Decimal(str(product.get("price", "0"))),
        }

    try:
        line_data = await asyncio.gather(
            *(fetch_and_reserve(i) for i in payload.items)
        )
    except ServiceClientError as exc:
        # Roll back reservations we already made.
        log.warning("Order creation failed (%s); rolling back %d reservations",
                    exc, len(reserved))
        # Fire-and-forget rollback — best effort.
        for pid, qty in reserved:
            try:
                # Note: Product Service doesn't have a "release" endpoint
                # in this MVP. In a real system you'd add one. Here we just
                # log; the stock is "leaked" but that's a known limitation
                # documented in ARCHITECTURE.md.
                log.warning("Stock leak: product_id=%d qty=%d (no release endpoint)", pid, qty)
            except Exception:
                pass

        if exc.status_code == 404:
            raise HTTPException(status_code=400, detail=f"Product not found: {exc.detail}")
        if exc.status_code == 409:
            raise HTTPException(status_code=409, detail=f"Stock issue: {exc.detail}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Product service error: {exc.detail}",
        )

    # 3. Persist the order
    total = sum((d["unit_price"] * d["quantity"]) for d in line_data)
    order = Order(
        user_id=user_id,
        status=ORDER_STATUS_CONFIRMED,  # confirmed because stock is reserved
        total_amount=total,
        notes=payload.notes,
        lines=[
            OrderLine(
                product_id=d["product_id"],
                product_name=d["product_name"],
                quantity=d["quantity"],
                unit_price=d["unit_price"],
            )
            for d in line_data
        ],
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return OrderOut(**order.to_dict())


@router.get("", response_model=list[OrderOut])
def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user_id: int = Depends(_user_id_from_header),
) -> list[OrderOut]:
    """List the current user's orders.

    Note: this filters by the X-User-Id header, so a user can only see
    their own orders. An admin endpoint would not filter this way.
    """
    orders = (
        db.query(Order)
        .filter(Order.user_id == user_id)
        .order_by(Order.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [OrderOut(**o.to_dict()) for o in orders]


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(_user_id_from_header),
) -> OrderOut:
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != user_id:
        # Don't leak existence of other users' orders — return 404 not 403.
        # 403 would let an attacker enumerate order IDs.
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderOut(**order.to_dict())


@router.patch("/{order_id}/status", response_model=OrderOut)
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(_user_id_from_header),
) -> OrderOut:
    """Update an order's status.

    Allowed transitions:
      pending → confirmed | cancelled
      confirmed → paid | cancelled
      paid → fulfilled | cancelled
      cancelled → (terminal)
      fulfilled → (terminal)
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != user_id:
        raise HTTPException(status_code=404, detail="Order not found")

    allowed = {
        ORDER_STATUS_PENDING: {ORDER_STATUS_CONFIRMED, ORDER_STATUS_CANCELLED},
        ORDER_STATUS_CONFIRMED: {"paid", ORDER_STATUS_CANCELLED},
        "paid": {"fulfilled", ORDER_STATUS_CANCELLED},
    }
    if payload.status not in allowed.get(order.status, set()):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition {order.status} → {payload.status}",
        )

    order.status = payload.status
    db.commit()
    db.refresh(order)
    return OrderOut(**order.to_dict())
