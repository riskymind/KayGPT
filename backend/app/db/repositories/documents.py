from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentStatus


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return await self.session.get(Document, document_id)

    async def get_owned(self, document_id: uuid.UUID, user_id: uuid.UUID) -> Document | None:
        result: Document | None = await self.session.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        return result

    async def list_for_user(
        self, user_id: uuid.UUID, *, conversation_id: uuid.UUID | None, include_global: bool
    ) -> Sequence[Document]:
        stmt = select(Document).where(Document.user_id == user_id)
        if conversation_id is not None:
            scope = Document.conversation_id == conversation_id
            stmt = stmt.where(
                or_(scope, Document.conversation_id.is_(None)) if include_global else scope
            )
        rows = await self.session.scalars(stmt.order_by(Document.created_at.desc()))
        return rows.all()

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> Sequence[Document]:
        rows = await self.session.scalars(
            select(Document).where(Document.conversation_id == conversation_id)
        )
        return rows.all()

    async def add(self, document: Document) -> Document:
        self.session.add(document)
        await self.session.flush()
        return document

    async def delete(self, document: Document) -> None:
        await self.session.delete(document)
        await self.session.flush()

    async def fail_stale_processing(self, older_than: datetime) -> int:
        """Documents left mid-ingestion by a crash/restart can never finish; mark them failed.

        Only rows untouched since `older_than` are affected, so ingestion running in another
        worker process is left alone.
        """
        result = await self.session.execute(
            update(Document)
            .where(
                Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING]),
                Document.updated_at < older_than,
            )
            .values(
                status=DocumentStatus.FAILED,
                error_message="Processing was interrupted by a server restart. Please re-upload.",
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)
