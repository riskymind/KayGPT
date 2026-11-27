"""Rebuild the vector index from the sources of truth.

Use after losing or replacing the Chroma store (new disk, new CHROMA_MODE, embedding model change):
  - memories are re-embedded from PostgreSQL;
  - documents are re-ingested from file storage (status goes pending → ready/failed).

Usage (from backend/): uv run python -m scripts.reindex [--memories] [--documents]
With no flag, both are rebuilt.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select, update

from app.core.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.llm.providers import create_embeddings
from app.models import Document, DocumentStatus, Memory
from app.rag.vector_store import MEMORIES_COLLECTION, ChromaVectorStore, VectorRecord
from app.services.document_service import ChunkingConfig, DocumentIngestor
from app.storage import create_storage


async def run(memories: bool, documents: bool) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    store = ChromaVectorStore.from_settings(settings, create_embeddings(settings))

    if memories:
        async with session_factory() as session:
            rows = (await session.scalars(select(Memory))).all()
        await store.upsert(
            MEMORIES_COLLECTION,
            [
                VectorRecord(id=str(m.id), text=m.content, metadata={"user_id": str(m.user_id)})
                for m in rows
            ],
        )
        print(f"Re-indexed {len(rows)} memories.")

    if documents:
        async with session_factory() as session:
            ids = list(
                (
                    await session.scalars(
                        select(Document.id).where(Document.status == DocumentStatus.READY)
                    )
                ).all()
            )
            await session.execute(
                update(Document).where(Document.id.in_(ids)).values(status=DocumentStatus.PENDING)
            )
            await session.commit()
        ingestor = DocumentIngestor(
            session_factory,
            create_storage(settings),
            store,
            ChunkingConfig(settings.rag_chunk_size, settings.rag_chunk_overlap),
        )
        for document_id in ids:
            await ingestor.ingest(document_id)
        print(f"Re-ingested {len(ids)} documents.")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the vector index.")
    parser.add_argument("--memories", action="store_true")
    parser.add_argument("--documents", action="store_true")
    args = parser.parse_args()
    both = not (args.memories or args.documents)
    asyncio.run(run(args.memories or both, args.documents or both))


if __name__ == "__main__":
    main()
