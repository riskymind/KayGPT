"""Deterministic chat model for automated tests and offline end-to-end runs (LLM_PROVIDER=fake).

Without a script it follows simple rules so the full tool loop can be exercised without an API key:
  "calculate <expr>"      -> calculator tool
  "remember <fact>"       -> remember_this tool
  "recall <query>"        -> recall_memory tool
  "search docs <query>"   -> search_uploaded_documents tool
  "search web <query>"    -> web_search tool
  anything else           -> "Echo: <message>"
After a tool returns, it answers "Result from <tool>: <output>".
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import uuid
from collections import deque
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from pydantic import Field, PrivateAttr

_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"^\s*calculate\s+(.+)$", re.I | re.S), "calculator", "expression"),
    (re.compile(r"^\s*remember\s+(.+)$", re.I | re.S), "remember_this", "memory"),
    (re.compile(r"^\s*recall\s+(.+)$", re.I | re.S), "recall_memory", "query"),
    (re.compile(r"^\s*search docs\s+(.+)$", re.I | re.S), "search_uploaded_documents", "query"),
    (re.compile(r"^\s*search web\s+(.+)$", re.I | re.S), "web_search", "query"),
]


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(part if isinstance(part, str) else str(part.get("text", "")) for part in content)


class FakeChatModel(BaseChatModel):
    """Scriptable fake. Pass `script` (a list of AIMessages) to control responses exactly."""

    script: list[AIMessage] = Field(default_factory=list)
    token_delay: float = 0.0
    model_id: str = "fake-model"
    _queue: deque[AIMessage] = PrivateAttr(default_factory=deque)
    _seen: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        self._queue = deque(self.script)

    @property
    def _llm_type(self) -> str:
        return "kaygpt-fake"

    @property
    def calls(self) -> list[list[BaseMessage]]:
        """Message lists the model was invoked with (for assertions)."""
        return self._seen

    def bind_tools(
        self, tools: Sequence[Any], *, tool_choice: str | None = None, **kwargs: Any
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self

    def _respond(self, messages: list[BaseMessage]) -> AIMessage:
        self._seen.append(list(messages))
        if self._queue:
            return self._queue.popleft()
        last = messages[-1]
        if isinstance(last, ToolMessage):
            return AIMessage(content=f"Result from {last.name}: {_text(last)}")
        if isinstance(last, HumanMessage):
            text = _text(last).strip()
            for pattern, tool_name, arg in _RULES:
                match = pattern.match(text)
                if match:
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": tool_name,
                                "args": {arg: match.group(1).strip()},
                                "id": f"call_{uuid.uuid4().hex[:12]}",
                                "type": "tool_call",
                            }
                        ],
                    )
            return AIMessage(content=f"Echo: {text}")
        return AIMessage(content="OK")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._respond(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for chunk in self._chunks(self._respond(messages)):
            if run_manager and isinstance(chunk.message.content, str):
                run_manager.on_llm_new_token(chunk.message.content, chunk=chunk)
            yield chunk

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for chunk in self._chunks(self._respond(messages)):
            if self.token_delay:
                await asyncio.sleep(self.token_delay)
            if run_manager and isinstance(chunk.message.content, str):
                await run_manager.on_llm_new_token(chunk.message.content, chunk=chunk)
            yield chunk

    @staticmethod
    def _chunks(message: AIMessage) -> list[ChatGenerationChunk]:
        if message.tool_calls:
            return [
                ChatGenerationChunk(
                    message=AIMessageChunk(
                        content=_text(message),
                        tool_call_chunks=[
                            {
                                "name": call["name"],
                                "args": _json(call["args"]),
                                "id": call["id"],
                                "index": i,
                                "type": "tool_call_chunk",
                            }
                            for i, call in enumerate(message.tool_calls)
                        ],
                    )
                )
            ]
        words = re.findall(r"\S+\s*|\s+", _text(message)) or [""]
        return [ChatGenerationChunk(message=AIMessageChunk(content=w)) for w in words]


def _json(value: Any) -> str:
    import json

    return json.dumps(value)


class HashingEmbeddings(Embeddings):
    """Bag-of-words hashing embeddings: texts sharing words are close in cosine distance.

    Offline stand-in for a real embedding model (tests, LLM_PROVIDER=fake). Not semantic.
    """

    def __init__(self, size: int = 256) -> None:
        self.size = size

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.size
        for token in re.findall(r"\w+", text.casefold()):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            vector[int.from_bytes(digest, "big") % self.size] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return (
            [v / norm for v in vector] if any(vector) else [1.0 / math.sqrt(self.size)] * self.size
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
