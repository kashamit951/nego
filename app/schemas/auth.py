from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserCreateRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    role: str = Field(..., pattern=r"^(admin|legal_reviewer|analyst|viewer)$")


class UserResponse(BaseModel):
    user_id: UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime


class ApiKeyCreateRequest(BaseModel):
    user_id: UUID
    scopes: list[str] = Field(default_factory=list)


class ApiKeyCreateResponse(BaseModel):
    key_id: UUID
    user_id: UUID
    key_prefix: str
    api_key: str
    created_at: datetime


class ApiKeyRevokeRequest(BaseModel):
    key_prefix: str = Field(..., min_length=2, max_length=32)


class ApiKeyRevokeResponse(BaseModel):
    revoked: bool


class MeResponse(BaseModel):
    user_id: UUID | None
    email: str
    role: str
    scopes: list[str]
    tenant_id: str
