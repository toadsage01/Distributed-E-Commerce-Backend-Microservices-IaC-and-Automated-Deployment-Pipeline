"""Pydantic request/response models for the User Service."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    created_at: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


class RefreshRequest(BaseModel):
    refresh_token: str


class APIKeyCreate(BaseModel):
    label: str = Field(default="default", max_length=128)


class APIKeyOut(BaseModel):
    id: int
    user_id: int
    label: str
    is_active: bool
    created_at: Optional[str] = None


class APIKeyCreated(APIKeyOut):
    """Returned once, right after creation — includes the raw key.
    The raw key is never retrievable again; only the hash is stored."""
    key: str
