from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Memory


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_owned(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> Memory | None:
        result: Memory | None = await self.session.scalar(
            select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
        )
        return result

    async def get_by_hash(self, user_id: uuid.UUID, content_hash: str) -> Memory | None:
        result: Memory | None = await self.session.scalar(
            select(Memory).where(Memory.user_id == user_id, Memory.content_hash == content_hash)
        )
        return result

    async def get_many_owned(
        self, ids: Sequence[uuid.UUID], user_id: uuid.UUID
    ) -> dict[uuid.UUID, Memory]:
        if not ids:
            return {}
        rows = await self.session.scalars(
            select(Memory).where(Memory.id.in_(ids), Memory.user_id == user_id)
        )
        return {m.id: m for m in rows}

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[Sequence[Memory], int]:
        total = await self.session.scalar(
            select(func.count()).select_from(Memory).where(Memory.user_id == user_id)
        )
        rows = await self.session.scalars(
            select(Memory)
            .where(Memory.user_id == user_id)
            .order_by(Memory.created_at.desc(), Memory.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return rows.all(), int(total or 0)

    async def add(self, memory: Memory) -> Memory:
        self.session.add(memory)
        await self.session.flush()
        return memory

    async def delete(self, memory: Memory) -> None:
        await self.session.delete(memory)
        await self.session.flush()
