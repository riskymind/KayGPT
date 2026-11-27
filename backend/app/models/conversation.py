from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(enum.StrEnum):
    COMPLETE = "complete"
    STOPPED = "stopped"  # client cancelled mid-generation; content is partial
    ERROR = "error"


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A chat thread. Its id is also the LangGraph checkpoint `thread_id`."""

    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    model_id: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (Index("ix_conversations_user_id_updated_at", "user_id", "updated_at"),)


class Message(UUIDPrimaryKeyMixin, Base):
    """UI-facing transcript. The agent's own memory of the thread lives in the checkpointer."""

    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default=MessageStatus.COMPLETE, server_default=MessageStatus.COMPLETE
    )
    model_id: Mapped[str | None] = mapped_column(String(100))
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )
    # clock_timestamp(), not now(): several messages written in one transaction must still order.
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())

    __table_args__ = (
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
        CheckConstraint("role IN ('user', 'assistant')", name="role"),
        CheckConstraint("status IN ('complete', 'stopped', 'error')", name="status"),
    )
