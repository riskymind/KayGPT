"""Chat turns: preparation (validation + persistence) and SSE streaming of the agent run.

Streaming protocol (one JSON object per SSE `data:` line; see docs/api-specification.md):
  start      {conversation_id, user_message_id, model, title}
  token      {content}
  tool_start {id, name, label}
  tool_end   {id, name, label, status}
  error      {code, message}                (terminal)
  done       {conversation_id, message_id, title}   (terminal)
Comment lines (": keep-alive") are sent while the agent is busy so proxies keep the stream open.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

import anyio
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.graph import CHATBOT_NODE, TOOLS_NODE, AgentGraph
from app.agents.state import AgentContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.db.repositories import ConversationRepository, MessageRepository
from app.models import Conversation, Message, MessageRole, MessageStatus
from app.schemas import ChatRequest
from app.services.conversation_service import title_from_message
from app.services.model_service import ModelService
from app.tools import TOOL_LABELS

logger = logging.getLogger(__name__)

Event = dict[str, Any]
CANCELLED_TOOL_RESULT = "Tool call was cancelled before it finished."


@dataclass(frozen=True)
class ChatTurn:
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    model_id: str
    text: str
    user_message_id: uuid.UUID
    title: str
    regenerate: bool


class ChatService:
    """Validates a chat request and persists the user side of the turn (request-scoped)."""

    def __init__(self, session: AsyncSession, models: ModelService) -> None:
        self.session = session
        self.models = models
        self.conversations = ConversationRepository(session)
        self.messages = MessageRepository(session)

    async def prepare(self, user_id: uuid.UUID, request: ChatRequest) -> ChatTurn:
        model_id = self.models.resolve(request.model)

        if request.regenerate:
            if request.conversation_id is None:
                raise ValidationFailedError("conversation_id is required to regenerate.")
            conversation = await self._owned(request.conversation_id, user_id)
            last_user = await self.messages.last_user_message(conversation.id)
            if last_user is None:
                raise ValidationFailedError("There is no message to regenerate.")
            await self.messages.delete_assistant_after(conversation.id, last_user)
            text, user_message_id = last_user.content, last_user.id
        else:
            if not request.message:
                raise ValidationFailedError("message is required.")
            text = request.message
            if request.conversation_id is not None:
                conversation = await self._owned(request.conversation_id, user_id)
            else:
                conversation = await self.conversations.add(
                    Conversation(user_id=user_id, title=title_from_message(text))
                )
            if conversation.title == "New chat":
                conversation.title = title_from_message(text)
            user_message = await self.messages.add(
                Message(
                    conversation_id=conversation.id,
                    role=MessageRole.USER,
                    content=text,
                    model_id=model_id,
                    meta={},
                )
            )
            user_message_id = user_message.id

        conversation.model_id = model_id
        await self.conversations.touch(conversation.id)
        await self.session.commit()
        return ChatTurn(
            user_id=user_id,
            conversation_id=conversation.id,
            model_id=model_id,
            text=text,
            user_message_id=user_message_id,
            title=conversation.title,
            regenerate=request.regenerate,
        )

    async def _owned(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation:
        conversation = await self.conversations.get_owned(conversation_id, user_id)
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        return conversation


def sse(event: Event) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def extract_text(content: Any) -> str:
    """Visible text from a message chunk. Non-text blocks (thinking, tool calls) are dropped."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type", "text") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


@dataclass
class _TurnProgress:
    parts: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    finished: bool = False

    @property
    def text(self) -> str:
        return "".join(self.parts)


class ChatStreamer:
    """Runs the agent for a prepared turn and yields SSE frames. Owns its DB sessions."""

    def __init__(
        self,
        graph: AgentGraph,
        session_factory: async_sessionmaker[AsyncSession],
        heartbeat_seconds: float = 15.0,
    ) -> None:
        self.graph = graph
        self.session_factory = session_factory
        self.heartbeat_seconds = heartbeat_seconds
        self._background: set[asyncio.Task[None]] = set()

    async def stream(self, turn: ChatTurn) -> AsyncIterator[str]:
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        progress = _TurnProgress()

        async def emit(event: Event) -> None:
            await queue.put(event)

        task = asyncio.create_task(self._produce(turn, progress, emit))
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        task.add_done_callback(lambda _: queue.put_nowait(None))

        try:
            yield sse(
                {
                    "type": "start",
                    "conversation_id": str(turn.conversation_id),
                    "user_message_id": str(turn.user_message_id),
                    "model": turn.model_id,
                    "title": turn.title,
                }
            )
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=self.heartbeat_seconds)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if event is None:
                    break
                yield sse(event)
        finally:
            if not task.done():
                # Client went away (or stop was pressed): cancel the run and let it persist
                # the partial answer. Shield the wait from our own cancellation.
                task.cancel()
                with anyio.CancelScope(shield=True), anyio.move_on_after(10):
                    await asyncio.gather(task, return_exceptions=True)

    async def _produce(
        self, turn: ChatTurn, progress: _TurnProgress, emit: Callable[[Event], Awaitable[None]]
    ) -> None:
        base_config: RunnableConfig = {"configurable": {"thread_id": str(turn.conversation_id)}}
        context = AgentContext(
            user_id=turn.user_id, conversation_id=turn.conversation_id, model_id=turn.model_id
        )
        try:
            await self._repair_dangling_tool_calls(base_config)
            graph_input: dict[str, Any] | None = {"messages": [HumanMessage(content=turn.text)]}
            run_config = base_config
            if turn.regenerate:
                fork = await self._regenerate_checkpoint(base_config)
                if fork is not None:
                    graph_input, run_config = None, fork

            async for mode, payload in self.graph.astream(
                cast(Any, graph_input),
                run_config,
                context=context,
                stream_mode=["messages", "updates"],
            ):
                if mode == "messages":
                    await self._on_message(payload, progress, emit)
                elif mode == "updates":
                    await self._on_update(payload, progress, emit)

            message_id = None
            if progress.text.strip():
                message_id = await self._save_assistant(turn, progress, MessageStatus.COMPLETE)
            progress.finished = True
            await emit(
                {
                    "type": "done",
                    "conversation_id": str(turn.conversation_id),
                    "message_id": str(message_id) if message_id else None,
                    "title": turn.title,
                }
            )
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                await self._on_cancel(turn, progress, base_config)
            raise
        except Exception as exc:
            logger.exception(
                "chat_generation_failed",
                extra={
                    "conversation_id": str(turn.conversation_id),
                    "error_type": type(exc).__name__,
                },
            )
            if progress.text.strip() and not progress.finished:
                with contextlib.suppress(Exception):
                    await self._save_assistant(turn, progress, MessageStatus.ERROR)
            await emit(
                {
                    "type": "error",
                    "code": "generation_failed",
                    "message": "The assistant could not complete this response. Please try again.",
                }
            )

    async def _on_message(
        self, payload: Any, progress: _TurnProgress, emit: Callable[[Event], Awaitable[None]]
    ) -> None:
        chunk, metadata = payload
        if (metadata or {}).get("langgraph_node") != CHATBOT_NODE:
            return
        if not isinstance(chunk, AIMessageChunk | AIMessage):
            return
        if chunk.tool_calls or getattr(chunk, "tool_call_chunks", None):
            return
        text = extract_text(chunk.content)
        if text:
            progress.parts.append(text)
            await emit({"type": "token", "content": text})

    async def _on_update(
        self, payload: Any, progress: _TurnProgress, emit: Callable[[Event], Awaitable[None]]
    ) -> None:
        if not isinstance(payload, dict):
            return
        for node, update in payload.items():
            messages = update.get("messages", []) if isinstance(update, dict) else []
            for message in messages:
                if node == CHATBOT_NODE and isinstance(message, AIMessage):
                    for call in message.tool_calls:
                        progress.tools.append(call["name"])
                        await emit(
                            {
                                "type": "tool_start",
                                "id": call.get("id"),
                                "name": call["name"],
                                "label": TOOL_LABELS.get(call["name"], call["name"]),
                            }
                        )
                elif node == TOOLS_NODE and isinstance(message, ToolMessage):
                    name = message.name or ""
                    await emit(
                        {
                            "type": "tool_end",
                            "id": message.tool_call_id,
                            "name": name,
                            "label": TOOL_LABELS.get(name, name),
                            "status": "error" if message.status == "error" else "success",
                        }
                    )

    async def _on_cancel(
        self, turn: ChatTurn, progress: _TurnProgress, config: RunnableConfig
    ) -> None:
        if progress.finished or not progress.text.strip():
            return
        try:
            await self._save_assistant(turn, progress, MessageStatus.STOPPED)
            # Keep the agent's view consistent with what the user saw.
            await self.graph.aupdate_state(
                config, {"messages": [AIMessage(content=progress.text)]}, as_node=CHATBOT_NODE
            )
        except Exception:
            logger.exception("chat_cancel_persist_failed")

    async def _repair_dangling_tool_calls(self, config: RunnableConfig) -> None:
        """A run cancelled during tool execution leaves an AIMessage whose tool calls have no
        results; Gemini rejects such histories. Close them with synthetic error results."""
        snapshot = await self.graph.aget_state(config)
        if snapshot.next != (TOOLS_NODE,):
            return
        messages = snapshot.values.get("messages", [])
        last = messages[-1] if messages else None
        if isinstance(last, AIMessage) and last.tool_calls:
            await self.graph.aupdate_state(
                config,
                {
                    "messages": [
                        ToolMessage(
                            content=CANCELLED_TOOL_RESULT,
                            tool_call_id=call["id"] or "",
                            name=call["name"],
                            status="error",
                        )
                        for call in last.tool_calls
                    ]
                },
                as_node=TOOLS_NODE,
            )

    async def _regenerate_checkpoint(self, config: RunnableConfig) -> RunnableConfig | None:
        """Most recent checkpoint where the last user message was added and not yet answered.
        Resuming from it forks the thread, so the old answer drops out of the agent's history."""
        async for snapshot in self.graph.aget_state_history(config):
            messages = snapshot.values.get("messages", [])
            if (
                snapshot.next == (CHATBOT_NODE,)
                and messages
                and isinstance(messages[-1], HumanMessage)
            ):
                return snapshot.config
        return None

    async def _save_assistant(
        self, turn: ChatTurn, progress: _TurnProgress, status: MessageStatus
    ) -> uuid.UUID | None:
        try:
            async with self.session_factory() as session:
                message = await MessageRepository(session).add(
                    Message(
                        conversation_id=turn.conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=progress.text,
                        status=status,
                        model_id=turn.model_id,
                        meta={"tools": sorted(set(progress.tools))} if progress.tools else {},
                    )
                )
                await ConversationRepository(session).touch(turn.conversation_id)
                await session.commit()
                return message.id
        except Exception:
            # e.g. the conversation was deleted mid-stream.
            logger.exception("assistant_message_save_failed")
            return None
