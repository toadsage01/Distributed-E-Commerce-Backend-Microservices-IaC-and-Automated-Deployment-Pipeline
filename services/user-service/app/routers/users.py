"""User profile endpoints.

The gateway forwards `X-User-Id` on every authenticated request, so internal
services trust that header (set by the gateway after JWT verification)
rather than re-verifying the JWT. This is the standard pattern — the
gateway is the single point of JWT verification.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import UserOut

router = APIRouter(prefix="/users", tags=["users"])


def _user_id_from_header(x_user_id: str = Header(..., alias="X-User-Id")) -> int:
    """Trust the X-User-Id header set by the gateway.

    This endpoint is only reachable from inside the VPC (security group
    restricts it to the gateway), so we trust the header. The gateway
    verified the JWT before forwarding; if a request reaches us with an
    X-User-Id header, it must have passed gateway auth.
    """
    try:
        return int(x_user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid X-User-Id header")


@router.get("/me", response_model=UserOut)
def get_me(
    db: Session = Depends(get_db),
    user_id: int = Depends(_user_id_from_header),
) -> UserOut:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(**user.to_public_dict())


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)) -> UserOut:
    """Public-ish lookup used by Order Service to validate user existence.

    Returns only public fields (no email unless the caller is the user
    themselves — that filtering is the gateway's job, not ours).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(**user.to_public_dict())
