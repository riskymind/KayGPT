"""Shared fixtures.

Database tests need PostgreSQL: set TEST_DATABASE_URL (e.g.
postgresql+psycopg://postgres:postgres@localhost:5432/kaygpt_test). The database is dropped and
recreated, then migrated with Alembic, once per session. Tests that need it are skipped otherwise.
No test calls Gemini or Tavily: the LLM, embeddings and web search are fakes.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import make_url

from app.core.config import Settings
from app.core.container import Container, ContainerOverrides
from app.llm.fake import FakeChatModel, HashingEmbeddings
from app.main import create_app
from app.rag.vector_store import ChromaVectorStore
from app.services.model_service import ModelInfo, ModelService
from app.storage import LocalStorage
from app.tools.web_search import SearchResult

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_DIR = Path(__file__).resolve().parent.parent
ORIGIN = "http://localhost:3000"
PASSWORD = "correct-horse-battery"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    url = make_url(TEST_DATABASE_URL)
    admin = url.set(database="postgres").render_as_string(hide_password=False)
    admin = admin.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{url.database}"')

    from alembic.config import Config

    from alembic import command

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    command.upgrade(cfg, "head")
    yield TEST_DATABASE_URL


@pytest.fixture
def clean_db(database_url: str) -> str:
    conninfo = database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE users, user_sessions, user_preferences, conversations, messages, "
            "memories, documents CASCADE"
        )
    return database_url


# ---------- Fakes ----------


class FakeSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str) -> list[SearchResult]:
        self.queries.append(query)
        return [SearchResult(title="KayGPT news", url="https://example.com/news", content=query)]


class ScriptableProvider:
    """Model provider whose models can be swapped per test (`provider.next_model = ...`)."""

    name = "fake"

    def __init__(self) -> None:
        self.models: dict[str, BaseChatModel] = {}
        self.factory: Callable[[str], BaseChatModel] = lambda model_id: FakeChatModel(
            model_id=model_id
        )

    def create(self, model_id: str) -> BaseChatModel:
        model = self.factory(model_id)
        self.models[model_id] = model
        return model


@pytest.fixture(scope="session")
def vector_store() -> ChromaVectorStore:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    client = chromadb.EphemeralClient(settings=ChromaSettings(anonymized_telemetry=False))
    return ChromaVectorStore(client, HashingEmbeddings())


def make_settings(database_url: str, tmp_path: Path, **extra: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "database_url": database_url,
        "llm_provider": "fake",
        "secret_key": "test-secret-key-test-secret-key-0123456789",
        "frontend_url": ORIGIN,
        "chroma_mode": "ephemeral",
        "upload_dir": str(tmp_path / "uploads"),
        "max_upload_size_mb": 1,
        "rate_limit_auth_per_minute": 1000,
        "rate_limit_chat_per_minute": 1000,
        "rate_limit_upload_per_minute": 1000,
        "sse_heartbeat_seconds": 5,
        "log_json": False,
        "log_level": "WARNING",
    }
    values.update(extra)
    return Settings(_env_file=None, **values)


@dataclass
class AppHarness:
    app: Any
    container: Container
    provider: ScriptableProvider
    search: FakeSearch
    checkpointer: Any
    settings: Settings
    clients: list[httpx.AsyncClient] = field(default_factory=list)

    def client(self) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
            headers={"Origin": ORIGIN},
            timeout=30,
        )
        self.clients.append(client)
        return client

    async def user_client(self, email: str | None = None) -> httpx.AsyncClient:
        """A client registered as a fresh user, with the CSRF header pre-set."""
        client = self.client()
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email or f"user-{uuid.uuid4().hex[:8]}@example.com",
                "password": PASSWORD,
            },
        )
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client


@pytest.fixture
async def harness(
    clean_db: str, tmp_path: Path, vector_store: ChromaVectorStore
) -> AsyncIterator[AppHarness]:
    settings = make_settings(clean_db, tmp_path)
    provider = ScriptableProvider()
    models = ModelService(
        [
            ModelInfo("fake-default", "Fake default", "fake", "test"),
            ModelInfo("fake-other", "Fake other", "fake", "test"),
        ],
        {"fake": provider},
        "fake-default",
    )
    search = FakeSearch()
    checkpointer = InMemorySaver()
    app = create_app(
        settings,
        ContainerOverrides(
            checkpointer=checkpointer,
            models=models,
            vector_store=vector_store,
            storage=LocalStorage(tmp_path / "uploads"),
            search_provider=search,
        ),
    )
    async with app.router.lifespan_context(app):
        harness = AppHarness(
            app=app,
            container=app.state.container,
            provider=provider,
            search=search,
            checkpointer=checkpointer,
            settings=settings,
        )
        yield harness
        for client in harness.clients:
            await client.aclose()


def parse_sse(body: str) -> list[dict[str, Any]]:
    import json

    events = []
    for frame in body.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


async def chat(client: httpx.AsyncClient, **body: Any) -> list[dict[str, Any]]:
    response = await client.post("/api/v1/chat/stream", json=body)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)
