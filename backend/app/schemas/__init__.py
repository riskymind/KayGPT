"""Pydantic v2 request/response schemas. These define the public API contract."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(APIModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------- Auth ----------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("display_name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(APIModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserOut
    csrf_token: str


# ---------- Models ----------


class ModelOut(BaseModel):
    id: str
    label: str
    provider: str
    description: str
    is_default: bool


class ModelsResponse(BaseModel):
    models: list[ModelOut]
    default_model: str


# ---------- Conversations / messages ----------


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    model_id: str | None = Field(default=None, max_length=100)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationOut(APIModel):
    id: uuid.UUID
    title: str
    model_id: str | None
    created_at: datetime
    updated_at: datetime


class MessageOut(APIModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    status: Literal["complete", "stopped", "error"]
    model_id: str | None
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageOut]
    has_more: bool


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str | None = Field(default=None, max_length=32_000)
    model: str | None = Field(default=None, max_length=100)
    regenerate: bool = False

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Message must not be empty.")
        return value


# ---------- Documents ----------


class DocumentOut(APIModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None
    filename: str
    content_type: str
    size_bytes: int
    status: Literal["pending", "processing", "ready", "failed"]
    error_message: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


# ---------- Memory ----------


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class MemoryOut(APIModel):
    id: uuid.UUID
    content: str
    source: str
    conversation_id: uuid.UUID | None
    created_at: datetime
    score: float | None = None


class MemoryCreateResult(BaseModel):
    memory: MemoryOut
    created: bool


# ---------- Preferences ----------


class PreferencesOut(APIModel):
    default_model: str | None
    theme: Literal["system", "light", "dark"]
    settings: dict[str, Any]


class PreferencesUpdate(BaseModel):
    default_model: str | None = Field(default=None, max_length=100)
    theme: Literal["system", "light", "dark"] | None = None
    settings: dict[str, Any] | None = None

    @field_validator("settings")
    @classmethod
    def _small(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(str(value)) > 4000:
            raise ValueError("settings is too large.")
        return value


# ---------- Health ----------


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, str]
