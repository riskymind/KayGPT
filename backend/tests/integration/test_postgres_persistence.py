"""Real PostgreSQL checkpointer (no InMemorySaver) and migration/model drift."""

from pathlib import Path

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.core.container import ContainerOverrides
from app.db.base import Base
from app.main import create_app
from app.rag.vector_store import ChromaVectorStore
from tests.conftest import ORIGIN, PASSWORD, FakeSearch, make_settings, parse_sse

pytestmark = pytest.mark.postgres


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    # Mirrors alembic/env.py: ignore LangGraph's checkpoint tables.
    return name in Base.metadata.tables if type_ == "table" else True


def test_migrations_match_models(clean_db: str) -> None:
    engine = create_engine(clean_db)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"include_name": include_name})
        diff = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert diff == [], f"Models and migrations differ; run `make migration`: {diff}"


async def test_postgres_checkpointer_persists_across_app_restarts(
    clean_db: str, tmp_path: Path, vector_store: ChromaVectorStore
) -> None:
    settings = make_settings(clean_db, tmp_path)

    def app_factory() -> object:
        return create_app(
            settings, ContainerOverrides(vector_store=vector_store, search_provider=FakeSearch())
        )

    app = app_factory()
    async with (
        app.router.lifespan_context(app),  # type: ignore[attr-defined]
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"Origin": ORIGIN}
        ) as client,
    ):
        reg = await client.post(
            "/api/v1/auth/register", json={"email": "pg@example.com", "password": PASSWORD}
        )
        client.headers["X-CSRF-Token"] = reg.json()["csrf_token"]
        response = await client.post("/api/v1/chat/stream", json={"message": "my name is Kay"})
        conv_id = parse_sse(response.text)[0]["conversation_id"]
        cookies = dict(client.cookies)
        csrf = reg.json()["csrf_token"]

    app = app_factory()  # new process-equivalent: fresh pool, fresh graph
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        state = await app.state.container.graph.aget_state(  # type: ignore[attr-defined]
            {"configurable": {"thread_id": conv_id}}
        )
        assert [m.content for m in state.values["messages"]] == [
            "my name is Kay",
            "Echo: my name is Kay",
        ]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://t",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            cookies=cookies,
        ) as client:
            response = await client.post(
                "/api/v1/chat/stream", json={"conversation_id": conv_id, "message": "again"}
            )
            assert parse_sse(response.text)[-1]["type"] == "done"
            assert (await client.delete(f"/api/v1/conversations/{conv_id}")).status_code == 204
        state = await app.state.container.graph.aget_state(  # type: ignore[attr-defined]
            {"configurable": {"thread_id": conv_id}}
        )
        assert state.values == {}
