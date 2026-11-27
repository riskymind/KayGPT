"""Conversation CRUD, transcript pagination and cross-store deletion."""

from __future__ import annotations

import logging
import uuid

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.repositories import ConversationRepository, DocumentRepository, MessageRepository
from app.models import Conversation, Message
from app.rag.vector_store import VectorStore
from app.services.document_service import purge_document_artifacts
from app.storage import StorageBackend

logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 60


def title_from_message(message: str) -> str:
    text = " ".join(message.split())
    if len(text) <= TITLE_MAX_LENGTH:
        return text or "New chat"
    return text[: TITLE_MAX_LENGTH - 1].rstrip() + "…"


class ConversationService:
    def __init__(
        self,
        session: AsyncSession,
        checkpointer: BaseCheckpointSaver[str],
        vector_store: VectorStore,
        storage: StorageBackend,
    ) -> None:
        self.session = session
        self.repo = ConversationRepository(session)
        self.messages = MessageRepository(session)
        self.checkpointer = checkpointer
        self.vector_store = vector_store
        self.storage = storage

    async def list_for_user(
        self, user_id: uuid.UUID, *, query: str | None, limit: int, offset: int
    ) -> tuple[list[Conversation], int]:
        rows, total = await self.repo.list_for_user(
            user_id, query=(query or "").strip() or None, limit=limit, offset=offset
        )
        return list(rows), total

    async def create(
        self, user_id: uuid.UUID, *, title: str | None, model_id: str | None
    ) -> Conversation:
        conversation = await self.repo.add(
            Conversation(user_id=user_id, title=(title or "New chat").strip(), model_id=model_id)
        )
        await self.session.commit()
        return conversation

    async def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
        conversation = await self.repo.get_owned(conversation_id, user_id)
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        return conversation

    async def rename(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, title: str
    ) -> Conversation:
        conversation = await self.get(user_id, conversation_id)
        conversation.title = title.strip()
        await self.session.commit()
        await self.session.refresh(conversation)
        return conversation

    async def list_messages(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        limit: int,
        before: uuid.UUID | None,
    ) -> tuple[list[Message], bool]:
        await self.get(user_id, conversation_id)
        return await self.messages.list_page(conversation_id, limit=limit, before=before)

    async def delete(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        """Delete the conversation everywhere: rows (cascade), checkpoints, vectors and files."""
        conversation = await self.get(user_id, conversation_id)
        documents = [
            (doc.id, doc.storage_key)
            for doc in await DocumentRepository(self.session).list_for_conversation(conversation_id)
        ]
        await self.repo.delete(conversation)
        await self.session.commit()

        try:
            await self.checkpointer.adelete_thread(str(conversation_id))
        except Exception:
            logger.warning(
                "checkpoint_delete_failed", extra={"conversation_id": str(conversation_id)}
            )
        await purge_document_artifacts(self.vector_store, self.storage, documents)
