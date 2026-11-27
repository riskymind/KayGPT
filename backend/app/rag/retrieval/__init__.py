"""Document retrieval scoped to the calling user and conversation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.rag.vector_store import DOCUMENTS_COLLECTION, VectorStore, Where

GLOBAL_SCOPE = ""  # Chroma metadata cannot be null; "" marks user-wide documents.


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: str
    filename: str
    text: str
    distance: float


def document_scope_filter(user_id: uuid.UUID, conversation_id: uuid.UUID | None) -> Where:
    scopes = [GLOBAL_SCOPE] if conversation_id is None else [str(conversation_id), GLOBAL_SCOPE]
    return {"$and": [{"user_id": str(user_id)}, {"conversation_id": {"$in": scopes}}]}


class DocumentRetriever:
    def __init__(self, vector_store: VectorStore, top_k: int = 4) -> None:
        self._store = vector_store
        self._top_k = top_k

    async def search(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID | None, query: str
    ) -> list[RetrievedChunk]:
        matches = await self._store.search(
            DOCUMENTS_COLLECTION,
            query,
            k=self._top_k,
            where=document_scope_filter(user_id, conversation_id),
        )
        return [
            RetrievedChunk(
                document_id=str(m.metadata.get("document_id", "")),
                filename=str(m.metadata.get("filename", "uploaded document")),
                text=m.text,
                distance=m.distance,
            )
            for m in matches
        ]


def format_chunks(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "No relevant uploaded document content found."
    return "\n\n".join(
        f"[Source {i}: {chunk.filename}]\n{chunk.text}" for i, chunk in enumerate(chunks, start=1)
    )
