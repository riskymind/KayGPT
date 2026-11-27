# KayGPT Architecture

## System overview

```text
 Browser ──HTTPS──▶ Next.js (Vercel / container :3000)
                    │  pages, server components, /api/v1/* rewrite (same origin → first-party cookies)
                    ▼
                  FastAPI (Render / container :8000)  ── /api/v1
                    │
   ┌────────────────┼─────────────────────┬───────────────────┬──────────────┐
   ▼                ▼                     ▼                   ▼              ▼
PostgreSQL     LangGraph agent       ChromaDB             Storage          External APIs
 app tables    (one compiled graph,  documents +          local disk /     Gemini (LLM +
 + LangGraph   AsyncPostgresSaver)   memory collections   S3-compatible    embeddings), Tavily
 checkpoints
```

- **Frontend** (`frontend/`): Next.js App Router, TypeScript strict, Tailwind + shadcn/ui, TanStack Query. No AI logic. All API calls go through `frontend/services/*` to the same-origin path `/api/v1/*`, which `next.config.ts` rewrites to `BACKEND_URL`.
- **Backend** (`backend/app/`): FastAPI app factory with a lifespan that owns every shared resource (DB engine, psycopg pool, checkpointer, compiled graph, model registry, vector store, storage backend, search provider). Handlers are thin; logic lives in `services/`.

## Backend layers

| Layer | Package | Responsibility |
|---|---|---|
| HTTP | `api/v1/endpoints/*`, `api/deps.py` | Parse/validate, resolve dependencies, call a service, shape the response |
| Cross-cutting | `middleware/`, `core/` | Settings, JSON logging, request ids, CSRF, rate limiting, error mapping, password hashing/session tokens |
| Services | `services/*` | Business rules, transactions, ownership checks |
| Persistence | `db/repositories/*`, `models/*` | SQLAlchemy 2 typed models and focused queries |
| Agent | `agents/*`, `tools/*` | Graph, prompts, nodes, tool implementations |
| RAG | `rag/*`, `storage/*` | Loaders, normalization, chunking, embeddings, vector store, file storage |

`app.state.container` (`core/container.py`) holds the long-lived resources; dependencies in `api/deps.py` read from it. Nothing request-scoped is stored at module level.

## Request lifecycle: `POST /api/v1/chat/stream`

1. Session cookie → `CurrentUser` dependency (sessions table lookup by SHA-256 of token). CSRF header checked by middleware for unsafe methods.
2. `ChatService.prepare()` resolves or creates the conversation (owned by the user), validates the model id against `ModelService`, stores the user `Message`, commits.
3. The stream generator calls `graph.astream(..., context=AgentContext(user_id, conversation_id, model_id, services…), config={"configurable": {"thread_id": conversation_id}}, stream_mode=["messages", "updates"])`.
4. Events are mapped to the SSE protocol (`token`, `tool_start`, `tool_end`, `error`, `done`) and pushed through a queue; a heartbeat comment is sent every 15 s while idle.
5. On completion the assistant message is saved. On client disconnect the producer task is cancelled, any partial text is saved with `status="stopped"`, and the checkpoint is repaired so dangling tool calls get synthetic `ToolMessage`s.

## Agent orchestration

```text
START → chatbot ──tools_condition──▶ tools ──▶ chatbot … → END
```

- State: `MessagesState`. System prompt is built per call (`agents/prompts.py`), never stored in state — same as the original.
- `chatbot` node reads `runtime.context.model_id`, gets a cached chat model with tools bound from `ModelService`, and invokes it.
- `tools` is the prebuilt `ToolNode`. Tools are built once at startup with their dependencies injected (session factory, vector store, retriever, search provider). Per-run identity comes from a `runtime: ToolRuntime[AgentContext]` parameter, hidden from the model, carrying `user_id`, `conversation_id` and `model_id`. This replaces the old `CURRENT_THREAD_ID` global; concurrent runs cannot see each other's identity (covered by `test_concurrent_runs_see_their_own_context` and `test_concurrent_users_tools_are_isolated`).
- Tools: `calculator` (AST evaluator), `web_search` (Tavily provider), `search_uploaded_documents` (RAG, scoped to user + conversation), `remember_this`, `recall_memory` (per user, semantic).
- Providers: `ModelService` maps model ids to a `ChatModelProvider` (`gemini` today, `fake` for tests/e2e — refused in production). Adding a provider is a new class plus config.

## RAG pipeline

1. `POST /documents/upload` validates extension, declared size, streamed size, and magic bytes (PDF `%PDF`, DOCX zip), decodes text files as UTF-8.
2. File saved through `StorageBackend` under a server-generated key `users/{user_id}/{document_id}{ext}`; the client filename is only metadata.
3. `Document` row created as `pending`; background task: `processing` → extract → normalize → chunk (900/150) → embed → upsert into Chroma with metadata `{user_id, conversation_id, document_id, filename, chunk_index}` → `ready` with `chunk_count`, or `failed` with a safe error message.
4. Retrieval filters on `user_id` AND (`conversation_id` = current) — the original per-conversation visibility is preserved and user isolation added.
5. Delete removes vectors, file, and row.

## Persistence

| Store | Contents | Prod location |
|---|---|---|
| PostgreSQL (app schema, Alembic) | users, sessions, conversations, messages, memories, documents, user_preferences | Render Postgres / compose `postgres` |
| PostgreSQL (LangGraph tables, `checkpointer.setup()`) | checkpoints keyed by `thread_id = conversation.id` | same database |
| Chroma | `kaygpt_documents`, `kaygpt_memories` collections | Render persistent disk or Chroma server (`CHROMA_MODE=http`) |
| File storage | Original uploads | Persistent disk (`local`) or S3-compatible bucket (`s3`) |

Deleting a conversation deletes its messages, documents (and their vectors/files) and its checkpoint thread, keeping the stores in sync.

PostgreSQL and the file store are the sources of truth; the Chroma index can be rebuilt from them (`python -m scripts.reindex`). Pre-2.0 SQLite data can be imported with `python -m scripts.import_legacy_sqlite`.

## Security model

- Argon2id password hashing; login responses don't reveal whether an email exists, and timing is equalized with a dummy hash.
- Opaque session tokens (HttpOnly, SameSite=Lax, Secure in production), stored hashed and revocable server-side.
- CSRF: session-bound HMAC token in `X-CSRF-Token` on every mutation, plus an Origin allow-list.
- Authorization: every repository query filters by the owning `user_id`; vector searches filter by `user_id` metadata and are re-checked against PostgreSQL (memories).
- Uploads: extension allow-list, magic-byte/UTF-8 validation, size limits enforced while streaming, zip-bomb guard for DOCX, server-generated storage keys (no path traversal), display names sanitized.
- Calculator: AST whitelist evaluator with exponent/factorial bounds (no `eval`).
- Errors: generic messages to clients, details only in logs; request bodies and conversation content are never logged.
- Rate limits on auth, chat and upload (per IP, per process); explicit CORS; security headers on both apps.

See `docs/database-schema.md`, `docs/api-specification.md`, `docs/deployment.md`.
