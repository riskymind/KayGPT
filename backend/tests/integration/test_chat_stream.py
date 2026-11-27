"""Streaming protocol, persistence, tools, regenerate, cancellation and concurrent isolation."""

import asyncio
import uuid
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.llm.fake import FakeChatModel
from app.services.chat_service import ChatTurn
from tests.conftest import AppHarness, chat, parse_sse

pytestmark = pytest.mark.postgres


async def _messages(client: Any, conv_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/conversations/{conv_id}/messages")
    return list(response.json()["items"])


async def test_stream_protocol_and_persistence(harness: AppHarness) -> None:
    client = await harness.user_client()
    events = await chat(client, message="Hello there KayGPT")
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "done"
    assert set(types[1:-1]) == {"token"}
    assert (
        "".join(e["content"] for e in events if e["type"] == "token") == "Echo: Hello there KayGPT"
    )

    start, done = events[0], events[-1]
    assert start["model"] == "fake-default"
    assert start["title"] == "Hello there KayGPT"
    assert done["conversation_id"] == start["conversation_id"]

    stored = await _messages(client, start["conversation_id"])
    assert [(m["role"], m["content"], m["status"]) for m in stored] == [
        ("user", "Hello there KayGPT", "complete"),
        ("assistant", "Echo: Hello there KayGPT", "complete"),
    ]
    assert stored[1]["id"] == done["message_id"]
    assert stored[0]["id"] == start["user_message_id"]


async def test_tool_events_do_not_leak_arguments(harness: AppHarness) -> None:
    client = await harness.user_client()
    events = await chat(client, message="calculate 125 * 48 / 6")
    tool_events = [e for e in events if e["type"].startswith("tool")]
    assert [(e["type"], e["name"]) for e in tool_events] == [
        ("tool_start", "calculator"),
        ("tool_end", "calculator"),
    ]
    assert tool_events[0]["label"] == "Calculator"
    assert tool_events[1]["status"] == "success"
    assert set(tool_events[0]) == {"type", "id", "name", "label"}  # no args exposed
    text = "".join(e["content"] for e in events if e["type"] == "token")
    assert text == "Result from calculator: 1000"
    assert "125 * 48" not in text  # tool input never streamed as tokens

    stored = await _messages(client, events[0]["conversation_id"])
    assert stored[-1]["metadata"] == {"tools": ["calculator"]}


async def test_web_search_tool_uses_provider(harness: AppHarness) -> None:
    client = await harness.user_client()
    events = await chat(client, message="search web latest kaygpt release")
    assert harness.search.queries == ["latest kaygpt release"]
    text = "".join(e["content"] for e in events if e["type"] == "token")
    assert "https://example.com/news" in text


async def test_continuity_and_model_selection(harness: AppHarness) -> None:
    client = await harness.user_client()
    first = await chat(client, message="my name is Kay")
    conv_id = first[0]["conversation_id"]
    second = await chat(client, conversation_id=conv_id, message="who am I?", model="fake-other")
    assert second[0]["model"] == "fake-other"
    model = harness.provider.models["fake-other"]
    assert isinstance(model, FakeChatModel)
    contents = [m.content for m in model.calls[-1]]
    assert "my name is Kay" in contents and "Echo: my name is Kay" in contents
    conv = (await client.get(f"/api/v1/conversations/{conv_id}")).json()
    assert conv["model_id"] == "fake-other"


async def test_invalid_requests(harness: AppHarness) -> None:
    client = await harness.user_client()
    unknown = await client.post(
        "/api/v1/chat/stream", json={"message": "hi", "model": "gemini-1.5-pro"}
    )
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_model"
    blank = await client.post("/api/v1/chat/stream", json={"message": "   "})
    assert blank.status_code == 422
    missing = await client.post(
        "/api/v1/chat/stream", json={"conversation_id": str(uuid.uuid4()), "message": "x"}
    )
    assert missing.status_code == 404
    regen = await client.post("/api/v1/chat/stream", json={"regenerate": True})
    assert regen.status_code == 422


async def test_regenerate_replaces_last_answer_and_forks_history(harness: AppHarness) -> None:
    client = await harness.user_client()
    harness.provider.factory = lambda model_id: FakeChatModel(
        model_id=model_id,
        script=[AIMessage(content="first answer"), AIMessage(content="second answer")],
    )
    events = await chat(client, message="tell me something")
    conv_id = events[0]["conversation_id"]
    regen = await chat(client, conversation_id=conv_id, regenerate=True)
    assert "".join(e["content"] for e in regen if e["type"] == "token") == "second answer"
    assert regen[0]["user_message_id"] == events[0]["user_message_id"]

    stored = await _messages(client, conv_id)
    assert [m["content"] for m in stored] == ["tell me something", "second answer"]

    state = await harness.container.graph.aget_state({"configurable": {"thread_id": conv_id}})
    contents = [m.content for m in state.values["messages"]]
    assert contents == ["tell me something", "second answer"]  # old answer not in agent history


async def test_model_failure_emits_error_event(harness: AppHarness) -> None:
    class Broken(FakeChatModel):
        def _respond(self, messages: list[Any]) -> AIMessage:
            raise RuntimeError("upstream API key=SECRET exploded")

    harness.provider.factory = lambda model_id: Broken(model_id=model_id)
    client = await harness.user_client()
    events = await chat(client, message="hello")
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "generation_failed"
    assert "SECRET" not in str(events)  # internal error details never reach the client


async def test_cancellation_persists_partial_answer_and_keeps_thread_usable(
    harness: AppHarness,
) -> None:
    """Simulates a client disconnect / Stop button mid-generation."""
    client = await harness.user_client()
    harness.provider.factory = lambda model_id: FakeChatModel(
        model_id=model_id,
        token_delay=0.05,
        script=[AIMessage(content=" ".join(f"word{i}" for i in range(100)))],
    )
    conv_id = (await client.post("/api/v1/conversations", json={})).json()["id"]
    service_turn = ChatTurn(
        user_id=uuid.UUID((await client.get("/api/v1/auth/me")).json()["user"]["id"]),
        conversation_id=uuid.UUID(conv_id),
        model_id="fake-default",
        text="write a long story",
        user_message_id=uuid.uuid4(),
        title="t",
        regenerate=False,
    )
    stream = harness.container.streamer.stream(service_turn)
    received = []
    async for frame in stream:
        received.extend(parse_sse(frame))
        if sum(1 for e in received if e["type"] == "token") >= 5:
            break
    await stream.aclose()  # what Starlette does when the client disconnects

    stored = await _messages(client, conv_id)
    assert len(stored) == 1
    assert stored[0]["status"] == "stopped"
    assert stored[0]["content"].startswith("word0 word1 word2 word3 word4")

    state = await harness.container.graph.aget_state({"configurable": {"thread_id": conv_id}})
    last = state.values["messages"][-1]
    assert isinstance(last, AIMessage) and last.content == stored[0]["content"]

    harness.provider.factory = lambda model_id: FakeChatModel(model_id=model_id)
    harness.container.models._bound.clear()
    follow_up = await chat(client, conversation_id=conv_id, message="continue")
    assert follow_up[-1]["type"] == "done"


async def test_dangling_tool_calls_are_repaired(harness: AppHarness) -> None:
    client = await harness.user_client()
    conv_id = (await chat(client, message="hello"))[0]["conversation_id"]
    config = {"configurable": {"thread_id": conv_id}}
    graph = harness.container.graph
    # Simulate a run killed between the model's tool call and the tool result.
    await graph.aupdate_state(
        config,
        {
            "messages": [
                HumanMessage("calc"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "calculator", "args": {"expression": "1+1"}, "id": "call-x"}
                    ],
                ),
            ]
        },
        as_node="chatbot",
    )
    assert (await graph.aget_state(config)).next == ("tools",)
    events = await chat(client, conversation_id=conv_id, message="still there?")
    assert events[-1]["type"] == "done"
    messages = (await graph.aget_state(config)).values["messages"]
    repaired = [m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == "call-x"]
    assert repaired and repaired[0].status == "error"


async def test_concurrent_users_tools_are_isolated(harness: AppHarness) -> None:
    """Two users saving memories at the same time must each get only their own."""
    clients = [await harness.user_client() for _ in range(4)]
    await asyncio.gather(
        *(chat(c, message=f"remember my favourite number is {i}") for i, c in enumerate(clients))
    )
    for i, client in enumerate(clients):
        memories = (await client.get("/api/v1/memory")).json()["items"]
        assert [m["content"] for m in memories] == [f"my favourite number is {i}"]

    results = await asyncio.gather(*(chat(c, message="recall favourite number") for c in clients))
    for i, events in enumerate(results):
        text = "".join(e["content"] for e in events if e["type"] == "token")
        assert f"my favourite number is {i}" in text
        for j in range(len(clients)):
            if j != i:
                assert f"number is {j}" not in text
