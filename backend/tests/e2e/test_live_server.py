"""Runs the real app under uvicorn (fake LLM, real Postgres checkpointer) and talks HTTP to it.

Checks what in-process tests cannot: tokens arrive incrementally over a real socket, and a
client disconnect mid-stream is detected and the partial answer persisted.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from tests.conftest import BACKEND_DIR, ORIGIN, PASSWORD

pytestmark = pytest.mark.postgres


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def server(clean_db: str, tmp_path: Path) -> Iterator[str]:
    port = _free_port()
    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": clean_db,
        "LLM_PROVIDER": "fake",
        "SECRET_KEY": "e2e-secret-key-e2e-secret-key-0123456789",
        "FRONTEND_URL": ORIGIN,
        "CHROMA_MODE": "persistent",
        "CHROMA_PERSIST_DIRECTORY": str(tmp_path / "chroma"),
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        "LOG_LEVEL": "WARNING",
        "SSE_HEARTBEAT_SECONDS": "1",
        "FAKE_LLM_TOKEN_DELAY": "0.02",
    }
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory", "--port", str(port)],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(150):
            try:
                if httpx.get(f"{base}/api/v1/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            proc.terminate()
            raise RuntimeError(proc.stderr.read().decode() if proc.stderr else "server failed")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _login(client: httpx.Client) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "live@example.com", "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def test_full_flow_over_http(server: str) -> None:
    with httpx.Client(base_url=server, headers={"Origin": ORIGIN}, timeout=30) as client:
        _login(client)

        # 1. Streaming arrives as separate SSE frames.
        frames: list[dict[str, object]] = []
        with client.stream(
            "POST", "/api/v1/chat/stream", json={"message": "calculate 2 ** 10"}
        ) as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"].startswith("no-cache")
            for line in response.iter_lines():
                if line.startswith("data: "):
                    frames.append(json.loads(line[6:]))
        types = [f["type"] for f in frames]
        assert types[0] == "start" and types[-1] == "done"
        assert "tool_start" in types and "tool_end" in types
        conv_id = frames[0]["conversation_id"]

        # 2. Upload + ingestion through the real background task.
        upload = client.post(
            "/api/v1/documents/upload",
            files={
                "file": ("facts.md", b"# Facts\nThe office cat is named Turing.", "text/markdown")
            },
            data={"conversation_id": str(conv_id)},
        )
        assert upload.status_code == 202
        doc_id = upload.json()["id"]
        for _ in range(50):
            status = client.get(f"/api/v1/documents/{doc_id}").json()["status"]
            if status == "ready":
                break
            time.sleep(0.1)
        assert status == "ready"


def test_client_disconnect_persists_partial_answer(server: str) -> None:
    with httpx.Client(base_url=server, headers={"Origin": ORIGIN}, timeout=30) as client:
        _login(client)
        long_message = "word " * 1000  # fake model echoes it word by word (20 ms per token)
        tokens = 0
        with client.stream(
            "POST", "/api/v1/chat/stream", json={"message": long_message.strip()}
        ) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    if event["type"] == "start":
                        conv_id = event["conversation_id"]
                    if event["type"] == "token":
                        tokens += 1
                        if tokens == 3:
                            break  # leaving the context manager closes the connection
        messages: list[dict[str, str]] = []
        for _ in range(50):
            messages = client.get(f"/api/v1/conversations/{conv_id}/messages").json()["items"]
            if len(messages) == 2:
                break
            time.sleep(0.1)
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assistant = messages[1]
        assert assistant["status"] == "stopped"
        assert len(assistant["content"].split()) < 200  # generation really stopped early
        assert ("Echo: " + long_message.strip()).startswith(assistant["content"])
