"""Graph topology (unchanged from the original KayGPT): START → chatbot ⇄ tools."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.agents.nodes import make_chatbot_node
from app.agents.state import AgentContext, AgentState
from app.services.model_service import ModelService

AgentGraph = CompiledStateGraph[AgentState, AgentContext, AgentState, AgentState]

CHATBOT_NODE = "chatbot"
TOOLS_NODE = "tools"


def build_graph(
    *,
    models: ModelService,
    tools: Sequence[BaseTool],
    checkpointer: BaseCheckpointSaver[str],
) -> AgentGraph:
    workflow = StateGraph(AgentState, context_schema=AgentContext)
    # cast: LangGraph's node protocols do not accept a plain async callable type.
    workflow.add_node(CHATBOT_NODE, cast(Any, make_chatbot_node(models, tools)))
    workflow.add_node(TOOLS_NODE, ToolNode(list(tools), name=TOOLS_NODE))
    workflow.add_edge(START, CHATBOT_NODE)
    workflow.add_conditional_edges(CHATBOT_NODE, tools_condition)
    workflow.add_edge(TOOLS_NODE, CHATBOT_NODE)
    return workflow.compile(checkpointer=checkpointer)
