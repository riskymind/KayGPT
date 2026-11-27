"""Long-term memory tools, scoped to the authenticated user via AgentContext."""

from __future__ import annotations

import logging

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.state import AgentContext
from app.core.exceptions import ValidationFailedError
from app.rag.vector_store import VectorStore
from app.services.memory_service import MemoryConfig, MemoryService, format_recalled

logger = logging.getLogger(__name__)


def build_memory_tools(
    session_factory: async_sessionmaker[AsyncSession],
    vector_store: VectorStore,
    config: MemoryConfig,
) -> list[BaseTool]:
    @tool
    async def remember_this(memory: str, runtime: ToolRuntime[AgentContext]) -> str:
        """Save an important user preference or fact into long-term memory.
        Use this when the user asks you to remember something."""
        ctx = runtime.context
        try:
            async with session_factory() as session:
                _, created = await MemoryService(session, vector_store, config).remember(
                    ctx.user_id, memory, conversation_id=ctx.conversation_id
                )
        except ValidationFailedError as exc:
            return f"Could not save memory: {exc.message}"
        except Exception:
            logger.exception("remember_failed")
            return "Saving memory failed due to a temporary error."
        return "Memory saved successfully." if created else "I already had that in memory."

    @tool
    async def recall_memory(query: str, runtime: ToolRuntime[AgentContext]) -> str:
        """Recall saved long-term memories about the user that are relevant to the query."""
        try:
            async with session_factory() as session:
                found = await MemoryService(session, vector_store, config).recall(
                    runtime.context.user_id, query
                )
        except Exception:
            logger.exception("recall_failed")
            return "Memory search is temporarily unavailable."
        return format_recalled(found)

    return [remember_this, recall_memory]
