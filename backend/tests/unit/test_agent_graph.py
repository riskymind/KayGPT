"""Agent graph tests with a fake model, in-memory checkpointer and no database."""

import asyncio
import uuid
from typing import Any

import pytest
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.graph import build_graph
from app.agents.prompts import build_system_prompt
from app.agents.state import AgentContext
from app.core.exceptions import ValidationFailedError
from app.llm.fake import FakeChatModel
from app.services.chat_service import extract_text
from app.services.model_service import ModelInfo, ModelService
from app.tools.calculator import build_calculator_tool


class _Provider:
    name = "fake"

    def __init__(self, model: FakeChatModel | None = None) -> None:
        self.model = model

    def create(self, model_id: str) -> FakeChatModel:
        return self.model or FakeChatModel(model_id=model_id)


def _models(model: FakeChatModel | None = None) -> ModelService:
    return ModelService(
        [ModelInfo("m1", "M1", "fake", ""), ModelInfo("m2", "M2", "fake", "")],
        {"fake": _Provider(model)},
        "m1",
    )


@tool
async def whoami(runtime: ToolRuntime[AgentContext]) -> str:
    """Return the caller identity from runtime context."""
    await asyncio.sleep(0.01)
    return f"{runtime.context.user_id}/{runtime.context.conversation_id}"


def _ctx(model_id: str = "m1") -> AgentContext:
    return AgentContext(user_id=uuid.uuid4(), conversation_id=uuid.uuid4(), model_id=model_id)


async def _run(graph: Any, ctx: AgentContext, text: str) -> list[Any]:
    result = await graph.ainvoke(
        {"messages": [HumanMessage(text)]},
        {"configurable": {"thread_id": str(ctx.conversation_id)}},
        context=ctx,
    )
    return list(result["messages"])


def test_model_service_rejects_unknown_model() -> None:
    models = _models()
    assert models.resolve(None) == "m1"
    assert models.resolve(" m2 ") == "m2"
    with pytest.raises(ValidationFailedError):
        models.resolve("gemini-1.5-pro")


def test_system_prompt_mentions_tools_and_date() -> None:
    prompt = build_system_prompt()
    for name in ["web_search", "search_uploaded_documents", "remember_this", "recall_memory"]:
        assert name in prompt
    assert "KayGPT" in prompt


def test_extract_text_drops_non_text_blocks() -> None:
    assert extract_text("hi") == "hi"
    assert (
        extract_text([{"type": "text", "text": "a"}, {"type": "thinking", "thinking": "x"}, "b"])
        == "ab"
    )
    assert extract_text(None) == ""


async def test_calculator_tool_loop() -> None:
    graph = build_graph(
        models=_models(), tools=[build_calculator_tool()], checkpointer=InMemorySaver()
    )
    messages = await _run(graph, _ctx(), "calculate 125 * 48 / 6")
    assert isinstance(messages[1], AIMessage) and messages[1].tool_calls[0]["name"] == "calculator"
    assert isinstance(messages[2], ToolMessage) and messages[2].content == "1000"
    assert messages[-1].content == "Result from calculator: 1000"


async def test_conversation_continuity_via_checkpointer() -> None:
    model = FakeChatModel()
    graph = build_graph(models=_models(model), tools=[], checkpointer=InMemorySaver())
    ctx = _ctx()
    await _run(graph, ctx, "my name is Kay")
    await _run(graph, ctx, "what is my name?")
    second_call = model.calls[-1]
    texts = [m.content for m in second_call]
    assert "my name is Kay" in texts  # history replayed from the checkpoint
    assert isinstance(second_call[0].content, str) and "KayGPT" in second_call[0].content


async def test_model_selected_per_run_via_context() -> None:
    created: list[str] = []

    class Tracking(_Provider):
        def create(self, model_id: str) -> FakeChatModel:
            created.append(model_id)
            return FakeChatModel(model_id=model_id)

    models = ModelService(
        [ModelInfo("m1", "", "fake", ""), ModelInfo("m2", "", "fake", "")],
        {"fake": Tracking()},
        "m1",
    )
    graph = build_graph(models=models, tools=[], checkpointer=InMemorySaver())
    await _run(graph, _ctx("m2"), "hello")
    await _run(graph, _ctx("m2"), "hello again")
    assert created == ["m2"]  # one graph, model chosen at runtime, model client cached


async def test_concurrent_runs_see_their_own_context() -> None:
    """Regression test for the old module-global thread id: tools must see their own run."""

    class CallsWhoami(FakeChatModel):
        def _respond(self, messages: list[Any]) -> AIMessage:
            last = messages[-1]
            if isinstance(last, ToolMessage):
                return AIMessage(content=str(last.content))
            return AIMessage(
                content="",
                tool_calls=[{"name": "whoami", "args": {}, "id": f"c-{uuid.uuid4().hex}"}],
            )

    tools: list[BaseTool] = [whoami]
    graph = build_graph(models=_models(CallsWhoami()), tools=tools, checkpointer=InMemorySaver())
    contexts = [_ctx() for _ in range(20)]
    results = await asyncio.gather(*(_run(graph, ctx, "who am i") for ctx in contexts))
    for ctx, messages in zip(contexts, results, strict=True):
        assert messages[-1].content == f"{ctx.user_id}/{ctx.conversation_id}"
