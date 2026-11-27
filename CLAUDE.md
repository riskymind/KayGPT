# CLAUDE.md

Guidance for Claude Code (claude.ai/code) in this repository.

## What this is

KayGPT is an agentic chat assistant, organized as a monorepo:
- `backend/`: FastAPI API (`/api/v1`), LangGraph agent (Gemini + tools), PostgreSQL, ChromaDB. Python 3.12, managed with **uv**.
- `frontend/`: Next.js 16 App Router UI. TypeScript strict, Tailwind 4, shadcn/ui (**Base UI** variant), TanStack Query. Managed with **pnpm**.
- `docs/`: architecture, API spec (including the SSE protocol), DB schema, deployment, development, audit and reports.

## Commands

```bash
make install | db-up | migrate | dev-backend | dev-frontend
make lint        # ruff check/format --check + eslint + prettier --check
make typecheck   # mypy --strict app scripts + tsc --noEmit
make test        # pytest + vitest
make migration m="msg"   # alembic autogenerate (review the file afterwards)
```
Backend directly: `cd backend && uv run pytest tests/unit` (no DB) or set `TEST_DATABASE_URL` (a throwaway DB, dropped and recreated) for the integration and e2e suites. Run a single test with `uv run pytest tests/integration/test_chat_stream.py -k regenerate`.
Frontend: `pnpm test`, `pnpm test:e2e` (needs running servers; `PW_CHANNEL=chrome` uses an installed Chrome), `pnpm build`.
Offline mode: `LLM_PROVIDER=fake` (scripted model: "calculate …", "remember …", "recall …", "search docs …", "search web …", else echo). It is refused in production.

## Backend architecture (backend/app)

- `main.py`: `create_app(settings, overrides)` factory. Run with `uvicorn app.main:create_app --factory`. **No import-time side effects**: settings are validated and clients are built in the lifespan.
- `core/container.py`: every long-lived resource (engine, session factory, psycopg pool + `AsyncPostgresSaver`, `ModelService`, vector store, storage, search provider, compiled graph, `ChatStreamer`, `DocumentIngestor`, rate limiter) is built once and stored on `app.state.container`. Tests swap pieces through `ContainerOverrides`. Don't add module-level singletons.
- Layers: `api/v1/endpoints` (thin) → `services` (business rules, commit transactions) → `db/repositories` (queries) → `models`. Dependencies are in `api/deps.py`.
- Auth: opaque session token in an HttpOnly cookie (`kaygpt_session`), stored as SHA-256 in `user_sessions`. Mutating requests need `X-CSRF-Token` = HMAC(secret, session token), which login/register/`/auth/me` return. Mutations also check `Origin`. `CurrentUser` enforces all of this.
- **Every query is scoped by `user_id`**. Resources owned by someone else return 404.
- Agent (`agents/`): `START → chatbot ⇄ tools` (prebuilt `ToolNode`/`tools_condition`), one compiled graph. Per-run identity goes in **LangGraph runtime context** `AgentContext(user_id, conversation_id, model_id)`; tools read it via `runtime: ToolRuntime[AgentContext]`. Never use globals for request state. The system prompt is built per call and not stored in state. Checkpoint `thread_id` = `str(conversation.id)`.
- Models: `services/model_service.py` + `llm/providers.py`. The allowed list comes from `GEMINI_MODELS`. Unknown ids → 422 (no silent fallback). Bound chat models are cached per model id.
- Streaming (`services/chat_service.py`): `ChatService.prepare()` validates and persists the user turn (JSON errors happen before streaming). `ChatStreamer.stream()` runs the graph in a producer task → queue → SSE frames, with keep-alive comments. Event types: `start, token, tool_start, tool_end, error, done`. Tool args/outputs are never sent. On disconnect the partial answer is saved with `status=stopped` and appended to the checkpoint. Dangling tool calls are repaired before the next turn. Regenerate forks from the checkpoint before the last answer. **If you change the event shape, update `frontend/lib/sse.ts`, `frontend/types/api.ts` and docs/api-specification.md.**
- RAG (`rag/`, `services/document_service.py`): upload validation (extension + magic bytes + size), server-generated storage keys, background ingestion `pending → processing → ready|failed`. Chroma metadata `{user_id, conversation_id or "", document_id, filename, chunk_index}`. Retrieval filters by user and by (this conversation or user-wide).
- Memory (`services/memory_service.py`): Postgres is the source of truth. Chroma `kaygpt_memories` is the search index. Exact duplicates are caught by `(user_id, content_hash)`, near-duplicates by vector distance.
- Storage (`storage/`): `local` or `s3`. Vector store (`rag/vector_store.py`): `VectorStore` protocol, Chroma implementation (`persistent` / `http` / `ephemeral`).
- Two persistence layers stay in sync on delete: messages (UI transcript) and checkpoints (agent memory). `ConversationService.delete` also removes the checkpoint thread, vectors and files.

## Frontend architecture (frontend/)

- All HTTP goes through `services/index.ts` → `lib/api-client.ts` (same-origin `/api/v1`, `credentials: include`, CSRF header from memory). `next.config.ts` rewrites `/api/v1/*` to `BACKEND_URL` **at build time**.
- Server state: TanStack Query hooks in `hooks/queries.ts`. Chat state: pure reducer in `lib/chat-reducer.ts` + `hooks/use-chat-stream.ts`. History loads merge (they never overwrite local streaming/error state).
- The chat UI lives in `app/(chat)/layout.tsx` (`AppShell` + `ChatRoute`) inside Suspense. Pages are placeholders, so moving `/` → `/c/{id}` mid-stream doesn't remount. `cacheComponents` is on: don't read cookies/headers in server components without Suspense.
- `proxy.ts` (Next 16 name for middleware; export `config`, not `proxyConfig`) redirects visitors without a session cookie to `/login`.
- shadcn components use Base UI: compose triggers with `render={<Button />}` (no `asChild`). Select uses `items` + `onValueChange`.

## Conventions

- Python: full type hints (mypy strict), Ruff (line length 100), async everywhere, `datetime` with UTC, no bare `except` without logging, user-facing error messages never include internals.
- Schema changes only through Alembic. `test_migrations_match_models` must pass.
- Tests never call Gemini or Tavily. Use `FakeChatModel`, `HashingEmbeddings`, `FakeSearch`.
- TS: strict, no `any`, Prettier (100 cols, Tailwind class sorting), components in `components/<area>/`.
- Don't log message content or secrets.

## Configuration

`.env.example` (repo root) documents every variable. The backend reads `.env` from `backend/` or the repo root. Production validation (`Settings.validate_runtime`) refuses to start without `GOOGLE_API_KEY`, `TAVILY_API_KEY` and a strong `SECRET_KEY`, and rejects `LLM_PROVIDER=fake`, non-PostgreSQL URLs and ephemeral Chroma.

## Deployment

Vercel (frontend, root dir `frontend`, env `BACKEND_URL`), Render Blueprint `render.yaml` (Docker backend + Postgres + persistent disk at `/data`, migrations in `preDeployCommand`), or `docker compose up --build`. Render's filesystem is ephemeral outside the disk. Use the disk or S3 + Chroma server. Details in docs/deployment.md. Never deploy or change secrets without the owner's approval.
