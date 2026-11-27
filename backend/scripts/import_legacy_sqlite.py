"""One-off import of the pre-2.0 SQLite data into PostgreSQL.

Copies conversations, chat messages and long-term memories from `data/chatbot_memory.db`
(the old SQLAlchemy/SQLite store) into the new schema under ONE existing user, and seeds each
conversation's LangGraph checkpoint from its messages so the agent keeps the context.
Uploaded documents are not imported (re-upload them; the old Chroma store has no owner info).

The source file is opened read-only and never modified or deleted.

Usage (from backend/, with DATABASE_URL set and migrations applied):
    uv run python -m scripts.import_legacy_sqlite --sqlite ../data/chatbot_memory.db \
        --email you@example.com [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import select

from app.core.config import get_settings
from app.core.container import _postgres_checkpointer
from app.db.session import create_engine, create_session_factory
from app.models import Conversation, Memory, Message, User
from app.services.memory_service import memory_hash, normalize_memory


def _ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _read_legacy(
    path: Path,
) -> tuple[list[sqlite3.Row], dict[str, list[sqlite3.Row]], list[sqlite3.Row]]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conversations = conn.execute(
            "SELECT thread_id, title, created_at, updated_at FROM conversations"
        ).fetchall()
        messages: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in conn.execute(
            "SELECT thread_id, role, content, created_at FROM chat_messages ORDER BY created_at, id"
        ):
            messages[row["thread_id"]].append(row)
        memories = conn.execute("SELECT memory, created_at FROM long_term_memory").fetchall()
    finally:
        conn.close()
    return conversations, messages, memories


async def run(sqlite_path: Path, email: str, dry_run: bool) -> None:
    settings = get_settings()
    conversations, messages, memories = _read_legacy(sqlite_path)
    print(
        f"Found {len(conversations)} conversations, "
        f"{sum(len(v) for v in messages.values())} messages, {len(memories)} memories."
    )
    if dry_run:
        return

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    seeded: list[tuple[uuid.UUID, list[BaseMessage]]] = []
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise SystemExit(f"No user with email {email}. Register in the app first.")

        for row in conversations:
            conv = Conversation(
                user_id=user.id,
                title=(row["title"] or "Imported chat")[:200],
                created_at=_ts(row["created_at"]),
                updated_at=_ts(row["updated_at"]),
            )
            session.add(conv)
            await session.flush()
            history: list[BaseMessage] = []
            for msg in messages.get(row["thread_id"], []):
                role = "user" if msg["role"] == "user" else "assistant"
                session.add(
                    Message(
                        conversation_id=conv.id,
                        role=role,
                        content=msg["content"] or "",
                        meta={"imported": True},
                        created_at=_ts(msg["created_at"]),
                    )
                )
                cls = HumanMessage if role == "user" else AIMessage
                history.append(cls(content=msg["content"] or ""))
            seeded.append((conv.id, history))

        seen: set[str] = set()
        for row in memories:
            text = normalize_memory(row["memory"] or "")
            digest = memory_hash(text)
            if not text or digest in seen:
                continue
            seen.add(digest)
            exists = await session.scalar(
                select(Memory).where(Memory.user_id == user.id, Memory.content_hash == digest)
            )
            if exists is None:
                session.add(
                    Memory(
                        user_id=user.id,
                        content=text,
                        content_hash=digest,
                        source="imported",
                        created_at=_ts(row["created_at"]),
                    )
                )
        await session.commit()

    # Seed checkpoints so the agent remembers imported threads.
    from app.agents.graph import CHATBOT_NODE, build_graph
    from app.services.model_service import ModelService

    async with _postgres_checkpointer(settings) as checkpointer:
        graph = build_graph(
            models=ModelService.from_settings(settings), tools=[], checkpointer=checkpointer
        )
        for conv_id, history in seeded:
            if history:
                await graph.aupdate_state(
                    {"configurable": {"thread_id": str(conv_id)}},
                    {"messages": history},
                    as_node=CHATBOT_NODE,
                )
    await engine.dispose()
    print(
        f"Imported {len(seeded)} conversations for {email}. "
        "Now run `python -m scripts.reindex --memories` to make memories searchable."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.sqlite, args.email, args.dry_run))


if __name__ == "__main__":
    main()
