"""Long-term user memory: per-user facts with semantic recall and duplicate suppression."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.db.repositories import MemoryRepository
from app.models import Memory
from app.rag.vector_store import MEMORIES_COLLECTION, VectorRecord, VectorStore

logger = logging.getLogger(__name__)

MAX_MEMORY_LENGTH = 2000
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class MemoryConfig:
    recall_top_k: int = 5
    recall_max_distance: float = 0.8
    duplicate_max_distance: float = 0.08


@dataclass(frozen=True)
class RecalledMemory:
    memory: Memory
    distance: float


def normalize_memory(text: str) -> str:
    return _WS.sub(" ", text).strip()


def memory_hash(text: str) -> str:
    return hashlib.sha256(normalize_memory(text).casefold().encode()).hexdigest()


class MemoryService:
    def __init__(self, session: AsyncSession, store: VectorStore, config: MemoryConfig) -> None:
        self.session = session
        self.repo = MemoryRepository(session)
        self.store = store
        self.config = config

    async def remember(
        self,
        user_id: uuid.UUID,
        content: str,
        *,
        conversation_id: uuid.UUID | None = None,
        source: str = "agent",
    ) -> tuple[Memory, bool]:
        """Store a memory. Returns (memory, created); created=False for a duplicate."""
        text = normalize_memory(content)
        if not text:
            raise ValidationFailedError("Memory must not be empty.")
        if len(text) > MAX_MEMORY_LENGTH:
            raise ValidationFailedError(f"Memory must be at most {MAX_MEMORY_LENGTH} characters.")

        content_hash = memory_hash(text)
        existing = await self.repo.get_by_hash(user_id, content_hash)
        if existing:
            return existing, False

        near = await self.store.search(
            MEMORIES_COLLECTION, text, k=1, where={"user_id": str(user_id)}
        )
        if near and near[0].distance <= self.config.duplicate_max_distance:
            match = await self.repo.get_owned(uuid.UUID(near[0].id), user_id)
            if match:
                return match, False

        memory = Memory(
            user_id=user_id,
            conversation_id=conversation_id,
            content=text,
            content_hash=content_hash,
            source=source,
        )
        try:
            await self.repo.add(memory)
        except IntegrityError:
            # Concurrent insert of the same fact.
            await self.session.rollback()
            existing = await self.repo.get_by_hash(user_id, content_hash)
            if existing:
                return existing, False
            raise
        # Index before commit: if indexing fails the row is rolled back, so the stores stay in sync.
        await self.store.upsert(
            MEMORIES_COLLECTION,
            [VectorRecord(id=str(memory.id), text=text, metadata={"user_id": str(user_id)})],
        )
        await self.session.commit()
        return memory, True

    async def recall(
        self, user_id: uuid.UUID, query: str, *, k: int | None = None
    ) -> list[RecalledMemory]:
        query = normalize_memory(query)
        if not query:
            return []
        matches = await self.store.search(
            MEMORIES_COLLECTION,
            query,
            k=k or self.config.recall_top_k,
            where={"user_id": str(user_id)},
        )
        relevant = [m for m in matches if m.distance <= self.config.recall_max_distance]
        ids = []
        for match in relevant:
            try:
                ids.append(uuid.UUID(match.id))
            except ValueError:
                continue
        rows = await self.repo.get_many_owned(ids, user_id)  # ownership re-checked in Postgres
        return [
            RecalledMemory(memory=rows[uuid.UUID(m.id)], distance=m.distance)
            for m in relevant
            if uuid.UUID(m.id) in rows
        ]

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Memory], int]:
        rows, total = await self.repo.list_for_user(user_id, limit=limit, offset=offset)
        return list(rows), total

    async def delete(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> None:
        memory = await self.repo.get_owned(memory_id, user_id)
        if memory is None:
            raise NotFoundError("Memory not found.")
        await self.repo.delete(memory)
        await self.session.commit()
        try:
            await self.store.delete(MEMORIES_COLLECTION, ids=[str(memory_id)])
        except Exception:
            # Orphaned vectors are harmless: recall re-checks rows in Postgres.
            logger.warning("memory_vector_delete_failed", extra={"memory_id": str(memory_id)})


def format_recalled(memories: list[RecalledMemory]) -> str:
    if not memories:
        return "No relevant saved memory found."
    return "\n".join(f"- {item.memory.content}" for item in memories)
