import pytest

from tests.conftest import AppHarness, chat

pytestmark = pytest.mark.postgres


async def test_conversation_crud_and_search(harness: AppHarness) -> None:
    client = await harness.user_client()
    created = await client.post("/api/v1/conversations", json={"title": "Trip planning"})
    assert created.status_code == 201
    conv_id = created.json()["id"]
    await client.post("/api/v1/conversations", json={"title": "Budget"})

    listing = (await client.get("/api/v1/conversations")).json()
    assert listing["total"] == 2
    assert [c["title"] for c in listing["items"]] == ["Budget", "Trip planning"]

    found = (await client.get("/api/v1/conversations", params={"q": "trip"})).json()
    assert [c["id"] for c in found["items"]] == [conv_id]
    # LIKE wildcards in the query are escaped.
    assert (await client.get("/api/v1/conversations", params={"q": "%"})).json()["total"] == 0

    renamed = await client.patch(f"/api/v1/conversations/{conv_id}", json={"title": "Japan trip"})
    assert renamed.json()["title"] == "Japan trip"

    assert (await client.delete(f"/api/v1/conversations/{conv_id}")).status_code == 204
    assert (await client.get(f"/api/v1/conversations/{conv_id}")).status_code == 404


async def test_users_cannot_see_each_others_conversations(harness: AppHarness) -> None:
    alice = await harness.user_client()
    bob = await harness.user_client()
    events = await chat(alice, message="secret plans")
    conv_id = events[0]["conversation_id"]

    assert (await bob.get("/api/v1/conversations")).json()["total"] == 0
    assert (await bob.get(f"/api/v1/conversations/{conv_id}")).status_code == 404
    assert (await bob.get(f"/api/v1/conversations/{conv_id}/messages")).status_code == 404
    assert (await bob.delete(f"/api/v1/conversations/{conv_id}")).status_code == 404
    assert (
        await bob.patch(f"/api/v1/conversations/{conv_id}", json={"title": "pwned"})
    ).status_code == 404
    hijack = await bob.post(
        "/api/v1/chat/stream", json={"conversation_id": conv_id, "message": "hi"}
    )
    assert hijack.status_code == 404
    assert (await alice.get(f"/api/v1/conversations/{conv_id}")).json()["title"] == "secret plans"


async def test_message_pagination(harness: AppHarness) -> None:
    client = await harness.user_client()
    events = await chat(client, message="message 0")
    conv_id = events[0]["conversation_id"]
    for i in range(1, 5):
        await chat(client, conversation_id=conv_id, message=f"message {i}")

    page = (
        await client.get(f"/api/v1/conversations/{conv_id}/messages", params={"limit": 4})
    ).json()
    assert page["has_more"] is True
    assert [m["content"] for m in page["items"]] == [
        "message 3",
        "Echo: message 3",
        "message 4",
        "Echo: message 4",
    ]
    older = (
        await client.get(
            f"/api/v1/conversations/{conv_id}/messages",
            params={"limit": 100, "before": page["items"][0]["id"]},
        )
    ).json()
    assert older["has_more"] is False
    assert len(older["items"]) == 6
    assert older["items"][0]["content"] == "message 0"


async def test_delete_conversation_removes_checkpoint_thread(harness: AppHarness) -> None:
    client = await harness.user_client()
    conv_id = (await chat(client, message="remember nothing"))[0]["conversation_id"]
    config = {"configurable": {"thread_id": conv_id}}
    assert harness.checkpointer.get_tuple(config) is not None
    assert (await client.delete(f"/api/v1/conversations/{conv_id}")).status_code == 204
    assert harness.checkpointer.get_tuple(config) is None


async def test_models_and_preferences(harness: AppHarness) -> None:
    client = await harness.user_client()
    models = (await client.get("/api/v1/models")).json()
    assert models["default_model"] == "fake-default"
    assert {m["id"] for m in models["models"]} == {"fake-default", "fake-other"}

    prefs = (await client.get("/api/v1/preferences")).json()
    assert prefs == {"default_model": None, "theme": "system", "settings": {}}
    updated = await client.put(
        "/api/v1/preferences", json={"default_model": "fake-other", "theme": "dark"}
    )
    assert updated.json()["default_model"] == "fake-other"
    assert updated.json()["theme"] == "dark"
    bad = await client.put("/api/v1/preferences", json={"default_model": "gpt-99"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_model"
