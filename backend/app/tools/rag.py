"""Document search tool. Scope comes from the run's AgentContext, never from model arguments."""

from __future__ import annotations

import logging

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, tool

from app.agents.state import AgentContext
from app.rag.retrieval import DocumentRetriever, format_chunks

logger = logging.getLogger(__name__)


def build_document_search_tool(retriever: DocumentRetriever) -> BaseTool:
    @tool
    async def search_uploaded_documents(query: str, runtime: ToolRuntime[AgentContext]) -> str:
        """Search the user's uploaded documents (PDF, DOCX, TXT, MD, PY, CSV) for relevant
        passages. Use when the user asks about an uploaded file, document, or notes."""
        ctx = runtime.context
        try:
            chunks = await retriever.search(
                user_id=ctx.user_id, conversation_id=ctx.conversation_id, query=query
            )
        except Exception:
            logger.exception("document_search_failed")
            return "Document search is temporarily unavailable."
        return format_chunks(chunks)

    return search_uploaded_documents
