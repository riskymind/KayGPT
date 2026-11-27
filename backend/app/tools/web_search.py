"""Web search tool and providers (Tavily by default)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)

MAX_SNIPPET_CHARS = 1200


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    content: str


class WebSearchProvider(Protocol):
    async def search(self, query: str) -> list[SearchResult]: ...


class WebSearchUnavailableError(RuntimeError):
    pass


class TavilySearchProvider:
    def __init__(self, api_key: str, max_results: int = 5) -> None:
        from tavily import AsyncTavilyClient

        self._client: Any = AsyncTavilyClient(api_key=api_key)
        self._max_results = max_results

    async def search(self, query: str) -> list[SearchResult]:
        response = await self._client.search(
            query=query,
            max_results=self._max_results,
            topic="general",
            search_depth="advanced",
        )
        return [
            SearchResult(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                content=str(item.get("content", ""))[:MAX_SNIPPET_CHARS],
            )
            for item in response.get("results", [])
        ]


class DisabledSearchProvider:
    """Used when TAVILY_API_KEY is not configured (development only)."""

    async def search(self, query: str) -> list[SearchResult]:
        raise WebSearchUnavailableError("Web search is not configured on this server.")


def format_results(results: list[SearchResult]) -> str:
    if not results:
        return "No web results found."
    return "\n\n".join(
        f"[{i}] {r.title}\nURL: {r.url}\n{r.content}" for i, r in enumerate(results, start=1)
    )


def build_web_search_tool(provider: WebSearchProvider) -> BaseTool:
    @tool
    async def web_search(query: str) -> str:
        """Search the web for current or time-sensitive information (news, prices, releases,
        current events, recent versions). Returns titles, URLs and snippets."""
        try:
            return format_results(await provider.search(query))
        except WebSearchUnavailableError as exc:
            return str(exc)
        except Exception:
            logger.exception("web_search_failed")
            return (
                "Web search failed. Answer from your own knowledge and say search was unavailable."
            )

    return web_search
