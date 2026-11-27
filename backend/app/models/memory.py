from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class Memory(UUIDPrimaryKeyMixin, Base):
    """Long-term fact about a user. Source of truth; the vector index holds a copy for search."""

    __tablename__ = "memories"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    content: Mapped[str] = mapped_column(Text)
    # SHA-256 of the normalized content, for exact-duplicate detection.
    content_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(20), default="agent", server_default="agent")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_memories_user_id_content_hash"),
        Index("ix_memories_user_id_created_at", "user_id", "created_at"),
    )
