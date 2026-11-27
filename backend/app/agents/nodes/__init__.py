"""Graph nodes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime

from app.agents.prompts import build_system_prompt
from app.agents.state import AgentContext, AgentState
from app.services.model_service import ModelService

ChatbotNode = Callable[[AgentState, Runtime[AgentContext]], Awaitable[dict[str, Any]]]


def make_chatbot_node(models: ModelService, tools: Sequence[BaseTool]) -> ChatbotNode:
    """The `chatbot` node: system prompt + history → selected model (with tools bound)."""

    async def chatbot(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
        llm = models.get_bound_model(runtime.context.model_id, tools)
        messages = [SystemMessage(content=build_system_prompt()), *state["messages"]]
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    return chatbot
