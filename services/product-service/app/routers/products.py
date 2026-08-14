"""Product catalog CRUD endpoints.

All write endpoints (POST/PATCH/DELETE) require the `X-User-Id` header set
by the gateway — the gateway has already verified the JWT, so we trust the
header. Read endpoints (GET) are public — products are part of the public
catalog and don't need auth (this is the typical e-commerce pattern: you
can browse without logging in).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Product
from ..schemas import ProductCreate, ProductOut, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


def _require_user_id(x_user_id: str = Header(..., alias="X-User-Id")) -> int:
    """Trust the gateway-set X-User-Id header for write operations."""
    try:
        return int(x_user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid X-User-Id header")


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    _: int = Depends(_require_user_id),
) -> ProductOut:
    product = Product(**payload.model_dump())
    db.add(product)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Product creation failed")
    db.refresh(product)
    return ProductOut(**product.to_dict())


@router.get("", response_model=list[ProductOut])
def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
) -> list[ProductOut]:
    """List products with simple pagination.

    `active_only` defaults to True — public catalog only shows active
    products. Admins (via a future role flag) would set this to False.
    """
    q = db.query(Product)
    if active_only:
        q = q.filter(Product.is_active.is_(True))
    products = q.order_by(Product.id.desc()).offset(skip).limit(limit).all()
    return [ProductOut(**p.to_dict()) for p in products]


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int,
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
) -> ProductOut:
    """Get a single product.

    By default hides soft-deleted (inactive) products — they 404 for end
    users. The `include_inactive` query param is the admin escape hatch.
    """
    q = db.query(Product).filter(Product.id == product_id)
    if not include_inactive:
        q = q.filter(Product.is_active.is_(True))
    product = q.first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductOut(**product.to_dict())


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    _: int = Depends(_require_user_id),
) -> ProductOut:
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Only update fields that were actually provided (PATCH semantics)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return ProductOut(**product.to_dict())


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: int = Depends(_require_user_id),
) -> Response:
    """Soft delete — flip is_active to False rather than removing the row.

    Hard deletes break referential integrity with orders. Soft delete
    keeps history queryable.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = False
    db.commit()
    return Response(status_code=204)


@router.post("/{product_id}/reserve", response_model=dict)
def reserve_stock(
    product_id: int,
    quantity: int = Query(..., gt=0),
    db: Session = Depends(get_db),
) -> dict:
    """Atomically decrement stock if available. Used by Order Service.

    Returns the new stock level. If stock is insufficient, returns 409.

    NOTE: This is the simplest atomic-reserve pattern — a single UPDATE
    statement with a WHERE clause. Real prod would use SELECT FOR UPDATE
    or advisory locks for higher contention, but this is correct for
    low-volume traffic and demonstrates the pattern.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.stock < quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Insufficient stock: have {product.stock}, need {quantity}",
        )
    product.stock -= quantity
    db.commit()
    db.refresh(product)
    return {"product_id": product_id, "remaining_stock": product.stock}
