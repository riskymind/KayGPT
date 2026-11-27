"""Agent tools. Built once at startup with their dependencies injected."""

from __future__ import annotations

from langchain_core.tools import BaseTool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.rag.retrieval import DocumentRetriever
from app.rag.vector_store import VectorStore
from app.services.memory_service import MemoryConfig
from app.tools.calculator import build_calculator_tool
from app.tools.memory import build_memory_tools
from app.tools.rag import build_document_search_tool
from app.tools.web_search import WebSearchProvider, build_web_search_tool

# Human-readable labels shown in the UI for tool progress events.
TOOL_LABELS: dict[str, str] = {
    "calculator": "Calculator",
    "web_search": "Web search",
    "search_uploaded_documents": "Document search",
    "remember_this": "Saving to memory",
    "recall_memory": "Recalling memory",
}


def build_tools(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    vector_store: VectorStore,
    retriever: DocumentRetriever,
    search_provider: WebSearchProvider,
    memory_config: MemoryConfig,
) -> list[BaseTool]:
    return [
        build_calculator_tool(),
        build_document_search_tool(retriever),
        *build_memory_tools(session_factory, vector_store, memory_config),
        build_web_search_tool(search_provider),
    ]
