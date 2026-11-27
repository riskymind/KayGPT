from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, MessageRole


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_owned(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> Conversation | None:
        result: Conversation | None = await self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        return result

    async def list_for_user(
        self, user_id: uuid.UUID, *, query: str | None, limit: int, offset: int
    ) -> tuple[Sequence[Conversation], int]:
        conditions = [Conversation.user_id == user_id]
        if query:
            pattern = f"%{_escape_like(query)}%"
            conditions.append(Conversation.title.ilike(pattern, escape="\\"))
        total = await self.session.scalar(
            select(func.count()).select_from(Conversation).where(*conditions)
        )
        rows = await self.session.scalars(
            select(Conversation)
            .where(*conditions)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return rows.all(), int(total or 0)

    async def add(self, conversation: Conversation) -> Conversation:
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def touch(self, conversation_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )

    async def delete(self, conversation: Conversation) -> None:
        await self.session.delete(conversation)
        await self.session.flush()


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, message: Message) -> Message:
        self.session.add(message)
        await self.session.flush()
        return message

    async def get(self, message_id: uuid.UUID) -> Message | None:
        return await self.session.get(Message, message_id)

    async def list_page(
        self, conversation_id: uuid.UUID, *, limit: int, before: uuid.UUID | None
    ) -> tuple[list[Message], bool]:
        """Newest-first page, returned oldest-first. `before` is a message id cursor."""
        stmt = select(Message).where(Message.conversation_id == conversation_id)
        if before is not None:
            anchor = select(Message.created_at).where(Message.id == before).scalar_subquery()
            stmt = stmt.where(Message.created_at < anchor)
        rows = list(
            (
                await self.session.scalars(
                    stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
                )
            ).all()
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()
        return rows, has_more

    async def last_user_message(self, conversation_id: uuid.UUID) -> Message | None:
        result: Message | None = await self.session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.role == MessageRole.USER)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        return result

    async def delete_assistant_after(self, conversation_id: uuid.UUID, message: Message) -> None:
        await self.session.execute(
            delete(Message).where(
                Message.conversation_id == conversation_id,
                Message.role == MessageRole.ASSISTANT,
                Message.created_at >= message.created_at,
            )
        )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
