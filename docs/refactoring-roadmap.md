# KayGPT — Refactoring Roadmap

Status: all phases implemented (2026-11-23). See `docs/implementation-report.md` for results and open items.

Each phase lists its acceptance criteria. Status is updated as phases complete.

## Key decisions

| Decision | Choice | Why |
|---|---|---|
| Repo layout | `frontend/` (Next.js) + `backend/` (FastAPI) monorepo | Independent deploys to Vercel and Render |
| Backend I/O | Fully async: SQLAlchemy 2 async + psycopg 3, `AsyncPostgresSaver`, `graph.astream` | Streaming + tool calls without blocking the event loop |
| Thread/user context in tools | LangGraph runtime context (`context_schema=AgentContext`, tools receive `ToolRuntime`) | Concurrency-safe, no globals |
| Model selection | One compiled graph; model id is part of the runtime context; chat models cached in `ModelService` | No per-model checkpointers; providers pluggable |
| Auth | Email + password (Argon2id), opaque session token in HttpOnly cookie, server-side `sessions` table, double-submit CSRF token | Revocable logout; no JWT secrets in browser |
| Cross-site cookies | Browser only talks to the Next.js origin; `/api/v1/*` rewritten to FastAPI | First-party cookies on Vercel ↔ Render |
| Memory retrieval | Postgres is source of truth; semantic index in a Chroma collection keyed by `user_id`; exact-dup check by content hash, near-dup by vector distance | Real relevance without adding pgvector |
| Rate limiting | Per user for chat/upload, per IP for auth; in-process | Forwarded IPs are spoofable when the API is called directly; user ids are not |
| Uploads | `StorageBackend` interface: `local` (dev, Docker volume, Render disk) and `s3` (any S3-compatible bucket, optional extra) | Survive ephemeral filesystems |
| Vector store | `VectorStore` wrapper around `langchain-chroma`; Chroma `persistent` (disk) or `http` (server) mode | Replaceable, persistent in prod |
| Ingestion | Upload returns `202` + document in `pending`; FastAPI background task moves it to `processing` → `ready`/`failed`; stale `processing` rows failed on startup | No request blocked on embeddings |
| Migrations | Alembic, run by the container entrypoint / Render `preDeployCommand` | Explicit, repeatable |
| Gemini 1.5 | Removed from defaults (retired upstream); list configurable via `GEMINI_MODELS` | Avoid selectable-but-broken models |

## Phases

### Phase 0 — Audit ✅
`docs/audit-report.md`, `docs/architecture.md`, this roadmap.

### Phase 1 — Foundation ✅
- `backend/pyproject.toml` (uv), Ruff, mypy, pytest config; `frontend/` via create-next-app (TS strict, Tailwind, ESLint), Prettier, Vitest, Playwright, shadcn/ui.
- `.env.example`, `.gitignore`, `.dockerignore`, `Makefile`; runtime data removed from the git index.
- **Accept:** `ruff`, `mypy`, `pytest` run on an empty app; `pnpm lint`, `pnpm typecheck`, `pnpm test` run.

### Phase 2 — Backend core ✅
- App factory + lifespan, Pydantic Settings, JSON logging, exception handlers, request-id middleware, CORS, CSRF, rate limiting.
- Models: `User`, `Session`, `Conversation`, `Message`, `Memory`, `Document`, `UserPreference`; Alembic initial migration.
- Repositories + services; auth, conversations, messages, preferences endpoints.
- **Accept:** integration tests against real Postgres for auth, ownership isolation, pagination.

### Phase 3 — Agent ✅
- `agents/` (state, prompts, nodes, graph, factory), tools with `ToolRuntime`, safe calculator, Tavily provider, memory tools, `AsyncPostgresSaver`.
- Chat service: SSE protocol, heartbeats, tool events, disconnect handling, dangling tool-call repair, regenerate via checkpoint fork.
- **Accept:** fake-LLM tests for streaming, tool calls, concurrent isolation, regenerate, cancellation.

### Phase 4 — RAG ✅
- Loaders, normalization, chunking, embeddings factory, vector store wrapper, storage backends, background ingestion with status.
- **Accept:** tests for validation (size, extension, magic bytes, traversal), ingestion status, retrieval isolation by user and conversation, delete removes vectors and file.

### Phase 5 — Frontend ✅
- Auth pages, chat layout, sidebar (search, rename, delete), model selector, streaming chat with markdown + code highlighting, copy, regenerate, stop, timestamps, attachments and documents panel, memory + preferences settings.
- **Accept:** Vitest/RTL component tests, typecheck, lint, production build.

### Phase 6 — Integration ✅
- Playwright e2e against the real backend with a fake LLM (`LLM_PROVIDER=fake`), concurrency test.

### Phase 7 — Deployment ✅
- Backend and frontend Dockerfiles, `docker-compose.yml`, `render.yaml`, Vercel config, docs.
- **Accept:** images build; compose config validates. Real deploys are **not** performed without owner approval.

### Phase 8 — Final review ✅
- Security/architecture checklist from the brief; `docs/implementation-report.md`.
