"""Document upload, background ingestion and lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import (
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaError,
    ValidationFailedError,
)
from app.db.repositories import ConversationRepository, DocumentRepository
from app.models import Document, DocumentStatus
from app.rag.chunking import normalize_text, split_text
from app.rag.loaders import (
    DocumentValidationError,
    ExtractionError,
    extract_text,
    file_type_for,
)
from app.rag.retrieval import GLOBAL_SCOPE
from app.rag.vector_store import DOCUMENTS_COLLECTION, VectorRecord, VectorStore
from app.storage import StorageBackend

logger = logging.getLogger(__name__)

_READ_CHUNK = 1024 * 1024
_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_size: int = 900
    chunk_overlap: int = 150


def display_filename(raw: str | None) -> str:
    """Filename for display only (never used as a path)."""
    name = (raw or "document").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_NAME_CHARS.sub("", name).strip(" .") or "document"
    return name[-255:]


async def read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    buffer = bytearray()
    while chunk := await upload.read(_READ_CHUNK):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise PayloadTooLargeError(
                f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit."
            )
    return bytes(buffer)


class DocumentService:
    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        vector_store: VectorStore,
        max_upload_bytes: int,
    ) -> None:
        self.session = session
        self.repo = DocumentRepository(session)
        self.storage = storage
        self.vector_store = vector_store
        self.max_upload_bytes = max_upload_bytes

    async def upload(
        self, user_id: uuid.UUID, upload: UploadFile, conversation_id: uuid.UUID | None
    ) -> Document:
        filename = display_filename(upload.filename)
        try:
            file_type = file_type_for(filename)
        except DocumentValidationError as exc:
            raise UnsupportedMediaError(str(exc)) from exc

        if upload.size is not None and upload.size > self.max_upload_bytes:
            raise PayloadTooLargeError(
                f"File exceeds the {self.max_upload_bytes // (1024 * 1024)} MB upload limit."
            )
        data = await read_limited(upload, self.max_upload_bytes)
        if not data:
            raise ValidationFailedError("The uploaded file is empty.")
        try:
            await asyncio.to_thread(file_type.validate, data)
        except DocumentValidationError as exc:
            raise UnsupportedMediaError(str(exc)) from exc

        if conversation_id is not None:
            owned = await ConversationRepository(self.session).get_owned(conversation_id, user_id)
            if owned is None:
                raise NotFoundError("Conversation not found.")

        document_id = uuid.uuid4()
        key = f"users/{user_id}/{document_id}{file_type.extension}"
        await self.storage.save(key, data, file_type.content_type)
        document = Document(
            id=document_id,
            user_id=user_id,
            conversation_id=conversation_id,
            filename=filename,
            content_type=file_type.content_type,
            extension=file_type.extension,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            storage_key=key,
            status=DocumentStatus.PENDING,
        )
        try:
            await self.repo.add(document)
            await self.session.commit()
        except Exception:
            await self.storage.delete(key)
            raise
        return document

    async def list_for_user(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID | None
    ) -> list[Document]:
        return list(
            await self.repo.list_for_user(
                user_id, conversation_id=conversation_id, include_global=True
            )
        )

    async def get(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.repo.get_owned(document_id, user_id)
        if document is None:
            raise NotFoundError("Document not found.")
        return document

    async def delete(self, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
        document = await self.get(user_id, document_id)
        key = document.storage_key
        await self.repo.delete(document)
        await self.session.commit()
        await purge_document_artifacts(self.vector_store, self.storage, [(document_id, key)])


async def purge_document_artifacts(
    vector_store: VectorStore,
    storage: StorageBackend,
    documents: list[tuple[uuid.UUID, str]],
) -> None:
    """Remove vectors and stored files for already-deleted document rows (best effort)."""
    for document_id, key in documents:
        try:
            await vector_store.delete(DOCUMENTS_COLLECTION, where={"document_id": str(document_id)})
        except Exception:
            logger.warning("document_vector_delete_failed", extra={"document_id": str(document_id)})
        try:
            await storage.delete(key)
        except Exception:
            logger.warning("document_file_delete_failed", extra={"document_id": str(document_id)})


class DocumentIngestor:
    """Runs after the upload response: extract → normalize → chunk → embed → index."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: StorageBackend,
        vector_store: VectorStore,
        chunking: ChunkingConfig,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.vector_store = vector_store
        self.chunking = chunking

    async def ingest(self, document_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            repo = DocumentRepository(session)
            document = await repo.get(document_id)
            if document is None or document.status != DocumentStatus.PENDING:
                return
            document.status = DocumentStatus.PROCESSING
            await session.commit()

            try:
                chunk_count = await self._index(document)
            except ExtractionError as exc:
                await self._fail(session, document, str(exc))
                return
            except Exception:
                logger.exception("document_ingest_failed", extra={"document_id": str(document_id)})
                await self._fail(session, document, "Indexing failed. Please try again later.")
                return

            # The row may have been deleted while we were indexing.
            if await session.get(Document, document_id, populate_existing=True) is None:
                await self.vector_store.delete(
                    DOCUMENTS_COLLECTION, where={"document_id": str(document_id)}
                )
                return
            document.status = DocumentStatus.READY
            document.chunk_count = chunk_count
            document.error_message = None
            await session.commit()
            logger.info(
                "document_ingested",
                extra={"document_id": str(document_id), "chunks": chunk_count},
            )

    async def _index(self, document: Document) -> int:
        data = await self.storage.read(document.storage_key)
        file_type = file_type_for(f"x{document.extension}")
        raw = await asyncio.to_thread(extract_text, data, file_type)
        text = normalize_text(raw)
        if not text:
            raise ExtractionError("No text could be extracted from this file.")
        chunks = split_text(
            text, chunk_size=self.chunking.chunk_size, chunk_overlap=self.chunking.chunk_overlap
        )
        records = [
            VectorRecord(
                id=f"{document.id}:{index}",
                text=chunk,
                metadata={
                    "user_id": str(document.user_id),
                    "conversation_id": (
                        str(document.conversation_id) if document.conversation_id else GLOBAL_SCOPE
                    ),
                    "document_id": str(document.id),
                    "filename": document.filename,
                    "chunk_index": index,
                },
            )
            for index, chunk in enumerate(chunks)
        ]
        await self.vector_store.delete(
            DOCUMENTS_COLLECTION, where={"document_id": str(document.id)}
        )
        await self.vector_store.upsert(DOCUMENTS_COLLECTION, records)
        return len(records)

    @staticmethod
    async def _fail(session: AsyncSession, document: Document, message: str) -> None:
        await session.rollback()
        fresh = await session.get(Document, document.id, populate_existing=True)
        if fresh is None:
            return
        fresh.status = DocumentStatus.FAILED
        fresh.error_message = message[:500]
        await session.commit()

    async def fail_stale(self, max_age: timedelta = timedelta(minutes=15)) -> int:
        async with self.session_factory() as session:
            count = await DocumentRepository(session).fail_stale_processing(
                datetime.now(UTC) - max_age
            )
            await session.commit()
            return count
