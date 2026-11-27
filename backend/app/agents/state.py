"""Graph state and per-run context.

State is `MessagesState` (persisted by the checkpointer). `AgentContext` is LangGraph runtime
context: supplied per `astream()` call, never persisted, and visible to nodes (`Runtime`) and
tools (`ToolRuntime`). It replaces the old module-global thread id, so concurrent runs cannot see
each other's identity.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from langgraph.graph import MessagesState

AgentState = MessagesState


@dataclass(frozen=True)
class AgentContext:
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    model_id: str
