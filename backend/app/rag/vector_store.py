"""Vector store abstraction with a ChromaDB implementation.

The rest of the app depends only on `VectorStore`; swapping Chroma for pgvector, Qdrant, etc.
means writing another class with these four methods.
Embeddings are computed here (via a LangChain `Embeddings`), not by Chroma, so the embedding
model is configured in one place.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.embeddings import Embeddings

from app.core.config import Settings

DOCUMENTS_COLLECTION = "kaygpt_documents"
MEMORIES_COLLECTION = "kaygpt_memories"

Metadata = Mapping[str, str | int | float | bool]
Where = dict[str, Any]


@dataclass(frozen=True)
class VectorRecord:
    id: str
    text: str
    metadata: Metadata = field(default_factory=dict)


@dataclass(frozen=True)
class VectorMatch:
    id: str
    text: str
    metadata: Metadata
    distance: float  # cosine distance: 0 = identical, 2 = opposite


class VectorStore(Protocol):
    async def upsert(self, collection: str, records: Sequence[VectorRecord]) -> None: ...

    async def search(
        self, collection: str, query: str, *, k: int, where: Where
    ) -> list[VectorMatch]: ...

    async def delete(
        self, collection: str, *, ids: Sequence[str] | None = None, where: Where | None = None
    ) -> None: ...

    async def healthcheck(self) -> bool: ...


class ChromaVectorStore:
    def __init__(self, client: Any, embeddings: Embeddings, batch_size: int = 64) -> None:
        self._client = client
        self._embeddings = embeddings
        self._batch_size = batch_size
        self._collections: dict[str, Any] = {}

    @classmethod
    def from_settings(cls, settings: Settings, embeddings: Embeddings) -> ChromaVectorStore:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        chroma_settings = ChromaSettings(anonymized_telemetry=False)
        if settings.chroma_mode == "http":
            client = chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
                ssl=settings.chroma_ssl,
                settings=chroma_settings,
            )
        elif settings.chroma_mode == "ephemeral":
            client = chromadb.EphemeralClient(settings=chroma_settings)
        else:
            client = chromadb.PersistentClient(
                path=settings.chroma_persist_directory, settings=chroma_settings
            )
        return cls(client, embeddings)

    def _collection(self, name: str) -> Any:
        collection = self._collections.get(name)
        if collection is None:
            collection = self._client.get_or_create_collection(
                name=name, metadata={"hnsw:space": "cosine"}, embedding_function=None
            )
            self._collections[name] = collection
        return collection

    async def upsert(self, collection: str, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        coll = await asyncio.to_thread(self._collection, collection)
        for start in range(0, len(records), self._batch_size):
            batch = records[start : start + self._batch_size]
            vectors = await self._embeddings.aembed_documents([r.text for r in batch])
            await asyncio.to_thread(
                coll.upsert,
                ids=[r.id for r in batch],
                documents=[r.text for r in batch],
                metadatas=[dict(r.metadata) for r in batch],
                embeddings=vectors,
            )

    async def search(
        self, collection: str, query: str, *, k: int, where: Where
    ) -> list[VectorMatch]:
        coll = await asyncio.to_thread(self._collection, collection)
        vector = await self._embeddings.aembed_query(query)
        result = await asyncio.to_thread(
            coll.query,
            query_embeddings=[vector],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        return [
            VectorMatch(id=i, text=d or "", metadata=m or {}, distance=float(dist))
            for i, d, m, dist in zip(ids, docs, metas, dists, strict=False)
        ]

    async def delete(
        self, collection: str, *, ids: Sequence[str] | None = None, where: Where | None = None
    ) -> None:
        if not ids and not where:
            return
        coll = await asyncio.to_thread(self._collection, collection)
        await asyncio.to_thread(coll.delete, ids=list(ids) if ids else None, where=where)

    async def healthcheck(self) -> bool:
        try:
            await asyncio.to_thread(self._client.heartbeat)
        except Exception:
            return False
        return True
