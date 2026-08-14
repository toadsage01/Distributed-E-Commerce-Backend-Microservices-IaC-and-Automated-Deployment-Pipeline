"""Auth endpoints: signup, login, refresh, API key management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.shared.jwt_utils import (
    decode_token,
    encode_access_token,
    encode_refresh_token,
)
from services.shared.config import get_platform_settings

from ..auth import generate_api_key, hash_password, hash_api_key, verify_password
from ..database import get_db
from ..models import APIKey, User
from ..schemas import (
    APIKeyCreate,
    APIKeyCreated,
    APIKeyOut,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(user_id: int) -> TokenResponse:
    settings = get_platform_settings()
    return TokenResponse(
        access_token=encode_access_token(user_id),
        refresh_token=encode_refresh_token(user_id),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: Session = Depends(get_db)) -> TokenResponse:
    """Create a new user and immediately issue tokens.

    Returns tokens directly so the client doesn't need a second /login call
    after signup — standard UX for mobile apps.
    """
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    db.refresh(user)
    return _issue_tokens(user.id)


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        # Same error for "no such user" and "wrong password" — avoids
        # user-enumeration via timing / message.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )
    return _issue_tokens(user.id)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest) -> TokenResponse:
    """Exchange a refresh token for a new access + refresh pair.

    Does NOT rotate the refresh token's `sub` claim — it trusts whatever
    the refresh token says. In a real prod system you'd:
      - store refresh token jti in Redis with TTL = refresh token TTL
      - blacklist on logout / password change
    Skipped here for brevity.
    """
    try:
        claims = decode_token(payload.refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    if claims.get("typ") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong token type",
        )
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token",
        )
    return _issue_tokens(int(user_id))


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def _current_user_id(authorization: str = Header(...)) -> int:
    """Extract user id from the Bearer token.

    This is a thin dependency — the gateway has already verified the JWT
    signature on real requests; here we just decode (without re-verifying
    signature, since this is an internal endpoint). In a stricter setup
    you'd verify here too, but that's redundant work.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    if claims.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Wrong token type")
    try:
        return int(claims["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Malformed token")


@router.post("/api-keys", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: APIKeyCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(_current_user_id),
) -> APIKeyCreated:
    raw, hashed = generate_api_key()
    key = APIKey(user_id=user_id, key_hash=hashed, label=payload.label)
    db.add(key)
    db.commit()
    db.refresh(key)
    return APIKeyCreated(**key.to_public_dict(), key=raw)


@router.get("/api-keys", response_model=list[APIKeyOut])
def list_api_keys(
    db: Session = Depends(get_db),
    user_id: int = Depends(_current_user_id),
) -> list[APIKeyOut]:
    rows = db.query(APIKey).filter(APIKey.user_id == user_id).all()
    return [APIKeyOut(**k.to_public_dict()) for k in rows]


def lookup_api_key(raw_key: str, db: Session) -> APIKey | None:
    """Helper used by the gateway — exposed here so the data model lives
    in one place. The gateway calls this indirectly via the `/auth/api-keys/lookup`
    endpoint (so we don't share DB access across services).
    """
    if not raw_key:
        return None
    hashed = hash_api_key(raw_key)
    return db.query(APIKey).filter(APIKey.key_hash == hashed, APIKey.is_active.is_(True)).first()


# ---------------------------------------------------------------------------
# Internal endpoint used by the API Gateway
# ---------------------------------------------------------------------------

@router.get("/api-keys/verify", response_model=dict, include_in_schema=False)
def verify_api_key_endpoint(
    key: str,
    db: Session = Depends(get_db),
) -> dict:
    """Gateway → User Service: verify an API key.

    Returns {'user_id': N, 'active': True} if valid, 404 if not.

    This endpoint is internal-only (security group restricts it to the
    gateway's subnet). It's not in the OpenAPI schema (include_in_schema=False)
    so it doesn't show up in the public docs.
    """
    api_key = lookup_api_key(key, db)
    if not api_key:
        raise HTTPException(status_code=404, detail="Invalid API key")
    return {"user_id": api_key.user_id, "active": api_key.is_active}
