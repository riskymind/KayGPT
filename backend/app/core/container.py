"""Long-lived application resources, created in the lifespan and stored on `app.state`.

Everything shared between requests lives here (no module-level singletons), which makes the app
testable: tests build a container with fakes through `build_container(..., overrides)`.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.graph import AgentGraph, build_graph
from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.db.session import create_engine, create_session_factory
from app.llm.providers import create_embeddings
from app.rag.retrieval import DocumentRetriever
from app.rag.vector_store import ChromaVectorStore, VectorStore
from app.services.chat_service import ChatStreamer
from app.services.document_service import ChunkingConfig, DocumentIngestor
from app.services.memory_service import MemoryConfig
from app.services.model_service import ModelService
from app.storage import StorageBackend, create_storage
from app.tools import build_tools
from app.tools.web_search import DisabledSearchProvider, TavilySearchProvider, WebSearchProvider

logger = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    checkpointer: BaseCheckpointSaver[str]
    models: ModelService
    vector_store: VectorStore
    storage: StorageBackend
    search_provider: WebSearchProvider
    graph: AgentGraph
    streamer: ChatStreamer
    ingestor: DocumentIngestor
    memory_config: MemoryConfig
    rate_limiter: RateLimiter
    session_ttl: timedelta
    _closers: list[Any] = field(default_factory=list)


@dataclass
class ContainerOverrides:
    """Test seams. Anything left as None is built from settings."""

    checkpointer: BaseCheckpointSaver[str] | None = None
    models: ModelService | None = None
    vector_store: VectorStore | None = None
    storage: StorageBackend | None = None
    search_provider: WebSearchProvider | None = None


@contextlib.asynccontextmanager
async def _postgres_checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver[str]]:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        conninfo=settings.psycopg_conninfo,
        max_size=settings.checkpoint_pool_size,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True, timeout=30)
    try:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()  # idempotent: creates/migrates LangGraph's own tables
        yield saver
    finally:
        await pool.close()


@contextlib.asynccontextmanager
async def build_container(
    settings: Settings, overrides: ContainerOverrides | None = None
) -> AsyncIterator[Container]:
    overrides = overrides or ContainerOverrides()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    async with contextlib.AsyncExitStack() as stack:
        stack.push_async_callback(engine.dispose)
        checkpointer: BaseCheckpointSaver[str]
        if overrides.checkpointer is not None:
            checkpointer = overrides.checkpointer
        else:
            checkpointer = await stack.enter_async_context(_postgres_checkpointer(settings))
        models = overrides.models or ModelService.from_settings(settings)
        vector_store = overrides.vector_store or ChromaVectorStore.from_settings(
            settings, create_embeddings(settings)
        )
        storage = overrides.storage or create_storage(settings)
        search_provider = overrides.search_provider or _search_provider(settings)
        memory_config = MemoryConfig(
            recall_top_k=settings.memory_recall_top_k,
            recall_max_distance=settings.memory_recall_max_distance,
            duplicate_max_distance=settings.memory_duplicate_max_distance,
        )
        tools = build_tools(
            session_factory=session_factory,
            vector_store=vector_store,
            retriever=DocumentRetriever(vector_store, top_k=settings.rag_top_k),
            search_provider=search_provider,
            memory_config=memory_config,
        )
        graph = build_graph(models=models, tools=tools, checkpointer=checkpointer)
        yield Container(
            settings=settings,
            engine=engine,
            session_factory=session_factory,
            checkpointer=checkpointer,
            models=models,
            vector_store=vector_store,
            storage=storage,
            search_provider=search_provider,
            graph=graph,
            streamer=ChatStreamer(graph, session_factory, settings.sse_heartbeat_seconds),
            ingestor=DocumentIngestor(
                session_factory,
                storage,
                vector_store,
                ChunkingConfig(settings.rag_chunk_size, settings.rag_chunk_overlap),
            ),
            memory_config=memory_config,
            rate_limiter=RateLimiter(),
            session_ttl=timedelta(days=settings.session_ttl_days),
        )


def _search_provider(settings: Settings) -> WebSearchProvider:
    if settings.tavily_api_key:
        return TavilySearchProvider(
            settings.tavily_api_key.get_secret_value(), settings.web_search_max_results
        )
    logger.warning("web_search_disabled", extra={"reason": "TAVILY_API_KEY not set"})
    return DisabledSearchProvider()
