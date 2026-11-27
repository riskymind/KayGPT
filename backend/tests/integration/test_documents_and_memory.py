import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.rag.vector_store import DOCUMENTS_COLLECTION, MEMORIES_COLLECTION
from tests.conftest import AppHarness, chat

pytestmark = pytest.mark.postgres


async def _upload(client: Any, name: str, data: bytes, conversation_id: str | None = None) -> Any:
    form = {"conversation_id": conversation_id} if conversation_id else {}
    return await client.post(
        "/api/v1/documents/upload", files={"file": (name, data, "text/plain")}, data=form
    )


async def _wait_ready(client: Any, doc_id: str) -> dict[str, Any]:
    for _ in range(50):
        doc = (await client.get(f"/api/v1/documents/{doc_id}")).json()
        if doc["status"] in ("ready", "failed"):
            return dict(doc)
        await asyncio.sleep(0.05)
    raise AssertionError("document never finished processing")


async def test_upload_ingest_retrieve_delete(harness: AppHarness) -> None:
    client = await harness.user_client()
    conv_id = (await client.post("/api/v1/conversations", json={})).json()["id"]
    text = "The launch code word is PINEAPPLE. " * 10
    response = await _upload(client, "../../notes.txt", text.encode(), conv_id)
    assert response.status_code == 202
    doc = response.json()
    assert doc["filename"] == "notes.txt"  # path components stripped
    assert doc["status"] == "pending"

    ready = await _wait_ready(client, doc["id"])
    assert ready["status"] == "ready" and ready["chunk_count"] >= 1

    events = await chat(client, conversation_id=conv_id, message="search docs " + text)
    answer = "".join(e["content"] for e in events if e["type"] == "token")
    assert "PINEAPPLE" in answer and "[Source 1: notes.txt]" in answer

    listing = (await client.get("/api/v1/documents", params={"conversation_id": conv_id})).json()
    assert [d["id"] for d in listing] == [doc["id"]]

    assert (await client.delete(f"/api/v1/documents/{doc['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/documents/{doc['id']}")).status_code == 404
    hits = await harness.container.vector_store.search(
        DOCUMENTS_COLLECTION, text, k=5, where={"document_id": doc["id"]}
    )
    assert hits == []
    assert list(Path(harness.settings.upload_dir).rglob("*.txt")) == []


async def test_documents_are_isolated_between_users_and_conversations(harness: AppHarness) -> None:
    alice = await harness.user_client()
    bob = await harness.user_client()
    chat_a = (await alice.post("/api/v1/conversations", json={})).json()["id"]
    chat_b = (await alice.post("/api/v1/conversations", json={})).json()["id"]
    secret = "Alice private document about ZEBRA migration. " * 5
    doc = (await _upload(alice, "private.md", secret.encode(), chat_a)).json()
    await _wait_ready(alice, doc["id"])

    assert (await bob.get(f"/api/v1/documents/{doc['id']}")).status_code == 404
    assert (await bob.delete(f"/api/v1/documents/{doc['id']}")).status_code == 404
    assert (await bob.get("/api/v1/documents")).json() == []
    bob_upload = await _upload(bob, "x.txt", b"hi", chat_a)  # Bob cannot attach to Alice's chat
    assert bob_upload.status_code == 404

    no_hits = "Result from search_uploaded_documents: No relevant uploaded document content found."

    def answer(events: list[dict[str, Any]]) -> str:
        return "".join(e["content"] for e in events if e["type"] == "token")

    assert answer(await chat(bob, message="search docs " + secret)) == no_hits
    assert (
        answer(await chat(alice, conversation_id=chat_b, message="search docs " + secret))
        == no_hits
    )
    assert "ZEBRA" in answer(
        await chat(alice, conversation_id=chat_a, message="search docs " + secret)
    )


async def test_upload_validation(harness: AppHarness) -> None:
    client = await harness.user_client()
    exe = await _upload(client, "virus.exe", b"MZ\x90")
    assert exe.status_code == 415
    fake_pdf = await _upload(client, "report.pdf", b"<html>not a pdf</html>")
    assert fake_pdf.status_code == 415
    binary_txt = await _upload(client, "notes.txt", b"\x00\x01\x02")
    assert binary_txt.status_code == 415
    empty = await _upload(client, "empty.txt", b"")
    assert empty.status_code == 422
    too_big = await _upload(client, "big.txt", b"a" * (1024 * 1024 + 1))  # limit is 1 MB in tests
    assert too_big.status_code == 413


async def test_ingestion_failure_is_reported(harness: AppHarness) -> None:
    client = await harness.user_client()
    doc = (await _upload(client, "blank.txt", b"   \n\n  ")).json()
    failed = await _wait_ready(client, doc["id"])
    assert failed["status"] == "failed"
    assert failed["error_message"] == "No text could be extracted from this file."


async def test_memory_api_dedup_search_delete_and_isolation(harness: AppHarness) -> None:
    alice = await harness.user_client()
    bob = await harness.user_client()

    first = await alice.post("/api/v1/memory", json={"content": "I prefer  dark mode"})
    assert first.status_code == 201 and first.json()["created"] is True
    dup = await alice.post("/api/v1/memory", json={"content": "i prefer dark mode"})
    assert dup.status_code == 200 and dup.json()["created"] is False
    assert dup.json()["memory"]["id"] == first.json()["memory"]["id"]
    await alice.post("/api/v1/memory", json={"content": "My dog is called Biscuit"})

    listing = (await alice.get("/api/v1/memory")).json()
    assert listing["total"] == 2

    hits = (await alice.get("/api/v1/memory", params={"q": "My dog is called Biscuit"})).json()
    assert hits["items"][0]["content"] == "My dog is called Biscuit"
    assert hits["items"][0]["score"] == pytest.approx(0, abs=1e-3)

    assert (await bob.get("/api/v1/memory")).json()["total"] == 0
    assert (await bob.get("/api/v1/memory", params={"q": "dog"})).json()["items"] == []
    memory_id = first.json()["memory"]["id"]
    assert (await bob.delete(f"/api/v1/memory/{memory_id}")).status_code == 404

    assert (await alice.delete(f"/api/v1/memory/{memory_id}")).status_code == 204
    assert (await alice.get("/api/v1/memory")).json()["total"] == 1
    alice_id = (await alice.get("/api/v1/auth/me")).json()["user"]["id"]
    remaining = await harness.container.vector_store.search(
        MEMORIES_COLLECTION, "I prefer dark mode", k=5, where={"user_id": alice_id}
    )
    assert [m.id for m in remaining] != [] and memory_id not in [m.id for m in remaining]


async def test_agent_memory_tools_dedupe(harness: AppHarness) -> None:
    client = await harness.user_client()
    first = await chat(client, message="remember I live in Lagos")
    second = await chat(client, message="remember I live in Lagos")
    assert "Memory saved successfully." in "".join(e.get("content", "") for e in first)
    assert "already had that" in "".join(e.get("content", "") for e in second)
    assert (await client.get("/api/v1/memory")).json()["total"] == 1
