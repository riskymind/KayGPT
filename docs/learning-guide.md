# KayGPT: A Guide to the Whole Project

This guide is for learning the codebase from scratch: what each part does, why it was built that way, and in what order to read the code. The other docs in this folder are references to look things up in. This one is meant to be read from top to bottom once.

> **How to use it:** read sections 1–3 first to build a mental model. Then follow section 4 (the life of one message) with the code open next to it. Everything after that is a deeper look at one subsystem at a time. Section 13 gives a suggested reading order and some exercises.

---

## Contents

1. [What KayGPT is](#1-what-kaygpt-is)
2. [The big picture](#2-the-big-picture)
3. [Five ideas that explain most of the code](#3-five-ideas-that-explain-most-of-the-code)
4. [The life of one message, end to end](#4-the-life-of-one-message-end-to-end)
5. [Backend: startup and the container](#5-backend-startup-and-the-container)
6. [Backend: the agent (LangGraph)](#6-backend-the-agent-langgraph)
7. [Backend: tools, memory and RAG](#7-backend-tools-memory-and-rag)
8. [Backend: auth and security](#8-backend-auth-and-security)
9. [Data: what lives where](#9-data-what-lives-where)
10. [Frontend](#10-frontend)
11. [Configuration, running and deploying](#11-configuration-running-and-deploying)
12. [Testing](#12-testing)
13. [Reading order and exercises](#13-reading-order-and-exercises)
14. [Gotchas and troubleshooting](#14-gotchas-and-troubleshooting)
15. [Glossary](#15-glossary)

---

## 1. What KayGPT is

KayGPT is a ChatGPT-style assistant. A user signs up, chats with a Gemini model, and the model can **use tools** while it answers:

| Tool | What it does |
|---|---|
| `calculator` | Safe arithmetic (an AST evaluator, never `eval`) |
| `web_search` | Current information via Tavily |
| `search_uploaded_documents` | Searches files the user uploaded (RAG) |
| `remember_this` / `recall_memory` | Long-term memory of facts about the user |

Answers **stream** to the browser token by token. The UI shows a "Web search…" style chip while a tool runs, and the user can **stop** or **regenerate** an answer.

The repo is a **monorepo** with two apps:

```text
kayGPT/
├── backend/    FastAPI + LangGraph + PostgreSQL + ChromaDB   (Python 3.12, uv)
├── frontend/   Next.js 16 App Router + TanStack Query         (TypeScript, pnpm)
├── docs/       reference docs (architecture, API, schema, deployment, …)
├── docker/     Dockerfiles
├── docker-compose.yml       full stack (postgres + backend + frontend)
├── docker-compose.dev.yml   only Postgres, for local development
├── render.yaml              Render Blueprint (production backend)
└── Makefile                 the commands you'll use daily
```

> The deleted root files you may see in `git status` (`app.py`, `agent.py`, `rag.py`, `templates/`…) are the **old v1** app, a single-file Flask-style prototype that used SQLite. Version 2 (this codebase) rebuilt it with the same features plus auth, isolation between users, and production deployment.

---

## 2. The big picture

```text
 Browser
   │  same-origin requests to /api/v1/*  (session cookie stays first-party)
   ▼
 Next.js (frontend, :3000)
   │  next.config.ts rewrites /api/v1/* → BACKEND_URL
   ▼
 FastAPI (backend, :8000)
   │
   ├── PostgreSQL ── app tables (users, conversations, messages, documents, memories…)
   │              └─ LangGraph checkpoint tables (the agent's own memory of each chat)
   ├── ChromaDB ──── vector index: document chunks + memory embeddings
   ├── Storage ───── uploaded files (local disk or S3)
   └── External ──── Gemini (chat + embeddings), Tavily (web search)
```

Key points:

- **The frontend has no AI logic.** It sends HTTP requests and renders the results. Everything intelligent happens in the backend.
- **The browser never talks to the backend directly.** It calls `/api/v1/...` on the Next.js host, and Next.js proxies the request. This keeps the session cookie on the same site. Without it, Vercel and Render on different domains would cause third-party cookie problems.
- **PostgreSQL is the source of truth.** Chroma is only a search index that can be rebuilt from Postgres and the stored files.

---

## 3. Five ideas that explain most of the code

Once these five ideas click, most of the files are easy to follow.

### Idea 1: Two transcripts per conversation

Every chat is stored **twice**, for different readers:

| | `messages` table | LangGraph **checkpoints** |
|---|---|---|
| Who reads it | The UI | The agent (LLM) |
| Contents | Clean user/assistant text + status + which tools were used | Every message, including tool calls and tool results |
| Keyed by | `conversation_id` | `thread_id = str(conversation.id)` |

The `messages` table is **never sent to the LLM**. The agent continues a conversation from its checkpoint. That's why delete, stop and regenerate have to keep both stores in sync (see sections 4 and 6).

### Idea 2: One container, no globals

Every long-lived object (DB engine, checkpointer, compiled graph, vector store, model service…) is built **once at startup** in [`core/container.py`](../backend/app/core/container.py) and stored on `app.state.container`. Request handlers get what they need through FastAPI dependencies in [`api/deps.py`](../backend/app/api/deps.py).

Why: tests can swap any piece (fake LLM, in-memory vector store) through `ContainerOverrides`, and importing a module never starts anything as a side effect.

### Idea 3: Per-run identity travels in "runtime context", not in globals

A tool like `recall_memory` has to know *which user* it's searching for. The v1 app used a module-level global, so two users chatting at the same time could see each other's data. Now each graph run gets an `AgentContext(user_id, conversation_id, model_id)` ([`agents/state.py`](../backend/app/agents/state.py)). Tools receive it through a hidden `runtime: ToolRuntime[AgentContext]` parameter that the LLM can't see or fake.

### Idea 4: Layers

```text
api/v1/endpoints  →  services  →  db/repositories  →  models
   (thin HTTP)      (rules,       (SQL queries,       (SQLAlchemy
                     commits)      always by user_id)   tables)
```

Endpoints parse input and call a service. Services hold the business rules and commit transactions. Repositories run queries, and **every query filters by `user_id`**. If you request another user's conversation, you get **404**, not 403, so the API doesn't reveal that it exists.

### Idea 5: Streaming is a producer/consumer queue

A chat answer is a long-running agent run. The backend runs it in a **background task (producer)** that pushes events into an `asyncio.Queue`. The HTTP response (**consumer**) reads from that queue and writes [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events). If the browser disconnects, the consumer's `finally` block cancels the producer, which saves whatever text was produced so far.

---

## 4. The life of one message, end to end

Follow this with the code open. The example: the user types **"What's the weather in Nairobi?"** in a new chat.

### Step 1: The browser sends it

1. [`components/chat/chat-input.tsx`](../frontend/components/chat/chat-input.tsx) → `ChatView` calls `send(text, model)` from [`hooks/use-chat-stream.ts`](../frontend/hooks/use-chat-stream.ts).
2. `send` dispatches a `"send"` action to the pure reducer [`lib/chat-reducer.ts`](../frontend/lib/chat-reducer.ts). It **optimistically** adds a user message and an empty assistant message with `status: "streaming"`, using temporary ids.
3. `chatService.stream()` ([`services/index.ts`](../frontend/services/index.ts)) sends `POST /api/v1/chat/stream` with `{ message, model, conversation_id: null }`, the session cookie, and the `X-CSRF-Token` header.

### Step 2: Next.js forwards it

The rewrite in [`next.config.ts`](../frontend/next.config.ts) proxies the request to FastAPI. `compress: false` is set on purpose: gzip would buffer the stream and break token-by-token delivery.

### Step 3: FastAPI authenticates it

[`endpoints/chat.py`](../backend/app/api/v1/endpoints/chat.py) depends on:

- `CurrentUser` ([`api/deps.py`](../backend/app/api/deps.py)) reads the `kaygpt_session` cookie, looks up its SHA-256 in `user_sessions`, then (because this is a POST) checks the `Origin` header and the CSRF token.
- `user_rate_limit("chat", …)`: a per-user sliding window.

### Step 4: `ChatService.prepare()` does the up-front work

In [`services/chat_service.py`](../backend/app/services/chat_service.py):

- It resolves the model id. An unknown id returns **422** with no silent fallback.
- It creates the conversation (with a title from the first message) because `conversation_id` was null.
- It saves the **user** `Message` row and **commits**.

All of this happens **before** the stream starts. Validation errors therefore come back as ordinary JSON errors, not as broken streams.

### Step 5: `ChatStreamer.stream()` runs the agent

- It immediately yields a `start` event: `{conversation_id, user_message_id, model, title}`.
- It starts `_produce()` as a background task, which:
  1. **Repairs dangling tool calls.** If a previous run was cancelled mid-tool, the checkpoint ends with an AI tool call that has no result, and Gemini rejects that. It adds synthetic error results.
  2. Calls `graph.astream({"messages": [HumanMessage(text)]}, config={thread_id}, context=AgentContext(...), stream_mode=["messages", "updates"])`.
  3. Translates LangGraph output into protocol events:
     - `messages` mode (token chunks from the `chatbot` node) → `token`
     - `updates` mode: an AIMessage with tool calls → `tool_start`, a ToolMessage → `tool_end`
  4. When the run ends, saves the **assistant** `Message` and emits `done`.
- While the agent is busy (for example waiting on a slow web search), the consumer sends `: keep-alive` comments every 15 s so proxies don't close the idle connection.

### Step 6: The agent decides

Inside the graph (section 6): the `chatbot` node sends the system prompt and the history to Gemini. Gemini answers with a **tool call** `web_search("weather Nairobi")`. `tools_condition` routes to the `tools` node, which runs the tool and appends the result. Then control goes back to `chatbot`, and Gemini now writes the final answer, which streams as tokens.

The browser receives:

```text
data: {"type":"start","conversation_id":"…","user_message_id":"…","model":"gemini-3.8-flash","title":"What's the weather in Nairobi?"}
data: {"type":"tool_start","id":"…","name":"web_search","label":"Web search"}
: keep-alive
data: {"type":"tool_end","id":"…","name":"web_search","label":"Web search","status":"success"}
data: {"type":"token","content":"Right now in Nairobi"}
data: {"type":"token","content":" it's 24°C…"}
data: {"type":"done","conversation_id":"…","message_id":"…","title":"…"}
```

Tool **arguments and outputs are never sent** to the browser, only names and labels.

### Step 7: The browser renders it

- [`lib/sse.ts`](../frontend/lib/sse.ts) splits the byte stream into frames and validates each one with a **zod** schema. Unknown or invalid frames are dropped.
- Each event is dispatched into the reducer: `start` swaps in the server's user message id, `token` appends text, `tool_*` updates the chips, and `done` marks the message complete.
- On `start` with a new conversation, the URL changes from `/` to `/c/{id}`. [`components/chat/chat-route.tsx`](../frontend/components/chat/chat-route.tsx) makes sure this **doesn't remount** the view, so the stream keeps going.

### What if the user presses Stop?

`stop()` aborts the `fetch`. The server sees the disconnect, and the `finally` in `stream()` cancels the producer. `_produce` catches `CancelledError` and runs `_on_cancel` inside a shielded scope. That saves the partial text with `status="stopped"` and appends the same text to the checkpoint, so **the agent remembers exactly what the user saw**.

### What if the user presses Regenerate?

`prepare()` deletes the last assistant message(s). `_regenerate_checkpoint()` walks the checkpoint history back to the moment just after the last user message was added. The graph is resumed **from that earlier checkpoint** (a fork), so the old answer disappears from the agent's history too.

### What if the model fails?

The exception is logged with its full traceback (server-side only). Any partial text is saved with `status="error"`, and the browser gets a generic `error` event: *"The assistant could not complete this response."* Internal details never reach the user.

---

## 5. Backend: startup and the container

Entry point: `uvicorn app.main:create_app --factory`.

[`main.py`](../backend/app/main.py) → `create_app(settings, overrides)`:

1. Builds the FastAPI app with CORS, the request-context middleware (request ids and JSON access logs) and the exception handlers.
2. In the **lifespan** (startup):
   - Configures logging.
   - Runs `settings.validate_runtime()`. In production it refuses to start without API keys, with a weak `SECRET_KEY`, with `LLM_PROVIDER=fake`, with a non-Postgres database, or with ephemeral Chroma.
   - `build_container()` creates everything: the SQLAlchemy engine, a psycopg pool, `AsyncPostgresSaver` (`.setup()` creates LangGraph's tables), `ModelService`, the Chroma vector store, storage, the search provider, the tools, the compiled graph, `ChatStreamer` and `DocumentIngestor`.
   - `fail_stale()` marks documents stuck in `processing` (because a restart interrupted them) as `failed`.

Other `core/` files:

| File | Purpose |
|---|---|
| [`config.py`](../backend/app/core/config.py) | `Settings` (pydantic-settings) reads `.env`. `GEMINI_MODELS` is the allow-list of selectable models. |
| [`security.py`](../backend/app/core/security.py) | Argon2 password hashing, session tokens, CSRF HMAC |
| [`exceptions.py`](../backend/app/core/exceptions.py) | `AppError` subclasses → consistent `{"error": {code, message}}` JSON |
| [`rate_limit.py`](../backend/app/core/rate_limit.py) | In-memory sliding window (per process) |
| [`logging.py`](../backend/app/core/logging.py) | JSON logs. Message content and secrets are never logged. |

---

## 6. Backend: the agent (LangGraph)

### The graph

[`agents/graph.py`](../backend/app/agents/graph.py):

```text
START → chatbot ──(tool calls?)──▶ tools ──▶ chatbot … ──(no tool calls)──▶ END
```

- **State** is `MessagesState`: a list of messages that LangGraph appends to and saves (checkpoints) after every step.
- **`chatbot` node** ([`agents/nodes/__init__.py`](../backend/app/agents/nodes/__init__.py)) reads `runtime.context.model_id`, gets the cached model-with-tools from `ModelService`, adds the **system prompt in front** and calls the model.
- **`tools` node** is LangGraph's prebuilt `ToolNode`, which runs whatever tools the model asked for.
- **`tools_condition`** routes to `tools` if the last AI message has tool calls, otherwise to `END`.

### The system prompt

[`agents/prompts.py`](../backend/app/agents/prompts.py) is rebuilt on **every call** (it includes today's date) and is **never stored** in state. Changing the prompt therefore affects old conversations immediately, and the checkpoints never fill up with stale prompts.

### Models

- [`services/model_service.py`](../backend/app/services/model_service.py) holds a registry of allowed model ids (from `GEMINI_MODELS`), a default, and `resolve()` (unknown id → 422). It caches one tool-bound model per id.
- [`llm/providers.py`](../backend/app/llm/providers.py): `GeminiProvider` (via `langchain-google-genai`), `FakeProvider`, and `create_embeddings()`.
- [`llm/fake.py`](../backend/app/llm/fake.py): `FakeChatModel`, a scripted model for tests and offline development. "calculate …", "remember …", "recall …", "search docs …" and "search web …" trigger tool calls. Anything else gets an echo reply. `HashingEmbeddings` provides deterministic offline embeddings.

**Current models** (Nov 2026, after Google retired the 2.5 family): `gemini-3.8-flash` (default), `gemini-3.1-pro-preview`, `gemini-3.5-flash-lite`. Embeddings: `gemini-embedding-001`.

### Checkpoints

The checkpointer saves the full state after every node, keyed by `thread_id`. That gives the agent memory across turns, and it's what makes **regenerate** (resume from an older checkpoint) and **stop** (`aupdate_state` to append the partial answer) possible.

---

## 7. Backend: tools, memory and RAG

### Tools

[`tools/__init__.py`](../backend/app/tools/__init__.py) builds the tool list **once** at startup and injects their dependencies (session factory, vector store, retriever, search provider). `TOOL_LABELS` holds the friendly names shown in the UI. The frontend keeps a copy in `chat-reducer.ts`.

Each tool follows the same pattern:

```python
@tool
async def recall_memory(query: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Docstring = what the LLM reads to decide when to call this."""
    user_id = runtime.context.user_id      # trusted identity, not an LLM argument
    try:
        ...
    except Exception:
        logger.exception("recall_failed")
        return "Memory search is temporarily unavailable."   # tools return text, never raise
```

Three things to notice: the docstring is the LLM's instruction, identity comes from `runtime` (the LLM can't spoof it), and failures come back to the model as text so it can explain the problem to the user.

### Memory

[`services/memory_service.py`](../backend/app/services/memory_service.py)

- **remember**: normalize whitespace → reject if empty or over 2000 characters → **exact-duplicate check** by `(user_id, sha256(casefold(text)))` → **near-duplicate check** by vector distance (≤ 0.08) → insert the row → upsert the vector → commit. The vector is indexed *before* the commit, so if indexing fails, the row is rolled back.
- **recall**: vector search filtered by `user_id` → keep matches with distance ≤ 0.8 → **re-check ownership in Postgres** before returning. Stale or orphaned vectors are therefore harmless.

### RAG (documents)

Upload → [`services/document_service.py`](../backend/app/services/document_service.py):

1. **Validate**: extension allow-list, size limit enforced *while streaming*, **magic bytes** (`%PDF`, DOCX zip with a zip-bomb guard), UTF-8 for text files ([`rag/loaders`](../backend/app/rag/loaders/__init__.py)).
2. **Store** under a server-generated key `users/{user_id}/{document_id}{ext}`. The client's filename is display metadata only, so path traversal isn't possible.
3. Create a `Document` row with status `pending` and schedule **background ingestion**.
4. `DocumentIngestor.ingest`: `processing` → extract text → normalize → **chunk** (900 characters, 150 overlap, [`rag/chunking`](../backend/app/rag/chunking/__init__.py)) → embed → upsert into Chroma `kaygpt_documents` with metadata `{user_id, conversation_id or "", document_id, filename, chunk_index}` → `ready`, or `failed` with a safe message.

Retrieval ([`rag/retrieval`](../backend/app/rag/retrieval/__init__.py)) filters by `user_id = me AND conversation_id IN (this chat, "")`. A document attached to a chat is searchable only there. A document uploaded with no conversation (`""`) is searchable in all of the user's chats.

[`rag/vector_store.py`](../backend/app/rag/vector_store.py) defines a `VectorStore` **protocol** with a Chroma implementation in three modes: `persistent` (a local directory), `http` (a Chroma server) and `ephemeral` (in memory, for tests).

### Storage

[`storage/`](../backend/app/storage/): a `StorageBackend` interface with `local` (a disk directory) and `s3` (any S3-compatible bucket) implementations.

---

## 8. Backend: auth and security

**Sessions, not JWTs.** On login, the server creates a random token, stores its **SHA-256** in `user_sessions`, and sets it in an **HttpOnly** cookie `kaygpt_session` (SameSite=Lax, Secure in production). Logout deletes the row, so sessions can be revoked immediately.

**CSRF.** Cookies are sent automatically by the browser, so a malicious site could otherwise trigger POSTs. Every mutating request must carry `X-CSRF-Token = HMAC(SECRET_KEY, session_token)`. Login, register and `/auth/me` return that value. The frontend keeps it **in memory only** ([`lib/api-client.ts`](../frontend/lib/api-client.ts)). The `Origin` header must also be in the allow-list.

**Passwords.** Argon2id hashing. Login uses the same error message and takes about the same time whether or not the email exists (it checks against a dummy hash), so attackers can't discover which emails are registered.

**Authorization.** Every query includes `user_id`. Vector searches filter by `user_id` metadata, and memories are re-checked in Postgres.

**Errors and logs.** Users get generic messages. Details go to the logs, which never contain message content.

**Rate limits.** Per IP for login and register; per user for chat and upload. They're in-memory and per process, so with several instances each instance has its own limit.

---

## 9. Data: what lives where

```text
users ─┬─< user_sessions
       ├── user_preferences (1:1: default_model, theme)
       ├─< conversations ─┬─< messages      (UI transcript)
       │                  ├─< documents
       │                  └─< memories      (SET NULL: memories outlive their chat)
       ├─< documents  (conversation_id NULL = available in every chat)
       └─< memories

conversations.id == LangGraph checkpoints.thread_id
```

| Store | Holds | Rebuildable? |
|---|---|---|
| Postgres (Alembic tables) | users, sessions, conversations, messages, documents, memories, preferences | **Source of truth.** Back it up. |
| Postgres (LangGraph tables) | checkpoints (agent memory) | No |
| Chroma | document chunks + memory vectors | Yes: `python -m scripts.reindex` |
| Storage (disk/S3) | original uploads | **No.** Back it up. |

**Deleting a conversation** ([`conversation_service.py`](../backend/app/services/conversation_service.py)) removes its messages, its documents (rows, vectors and files) and its checkpoint thread, keeping all four stores in sync.

Schema changes go **only through Alembic** (`make migration m="..."`, then review the generated file). The test `test_migrations_match_models` fails if the models and migrations drift. Full column details: [`database-schema.md`](database-schema.md).

---

## 10. Frontend

### Structure

```text
frontend/
├── app/
│   ├── (auth)/login, register     auth pages
│   ├── (chat)/layout.tsx          AppShell + ChatRoute (the whole chat UI lives here)
│   ├── (chat)/page.tsx, c/[id]/   placeholders, so URL changes don't remount the chat
│   └── layout.tsx                 root: providers, theme, fonts
├── components/
│   ├── chat/      chat-view, chat-input, message-item, markdown, model-selector…
│   ├── sidebar/   conversation list
│   ├── documents/ upload/list sheet
│   ├── settings/  theme + default model
│   └── ui/        shadcn components (Base UI variant)
├── hooks/         queries.ts (TanStack Query), use-chat-stream, use-selected-model…
├── lib/           api-client, sse, chat-reducer
├── services/      one function per API endpoint
├── types/api.ts   TypeScript mirror of the backend's JSON shapes
└── proxy.ts       redirects visitors without a session cookie to /login
```

### Two kinds of state

1. **Server state** (conversation list, documents, memories, models, preferences): **TanStack Query** hooks in [`hooks/queries.ts`](../frontend/hooks/queries.ts). They cache, refetch and invalidate after mutations.
2. **The live chat**: a **pure reducer** ([`lib/chat-reducer.ts`](../frontend/lib/chat-reducer.ts)) driven by [`use-chat-stream.ts`](../frontend/hooks/use-chat-stream.ts). Because it's pure, it's easy to unit test. History loads **merge** into it and never overwrite it: after the first load, local state wins because it holds streaming, stopped and error states that the server may not know about yet.

### Routing trick

The UI lives in the `(chat)` **layout**, not in the pages. When the first message creates a conversation, the URL moves to `/c/{id}`, but `ChatRoute` keeps the same `ChatView` instance (same React `key`), so the in-flight stream isn't interrupted. Navigating to a *different* chat bumps the key and mounts a fresh view.

### Model selection

[`use-selected-model.ts`](../frontend/hooks/use-selected-model.ts) picks, in order: the user's current choice → their saved preference → the server's default. Each candidate is used only if it's still in the server's model list, so retired model ids fall back safely.

### Conventions

- shadcn here uses **Base UI**, not Radix: compose triggers with `render={<Button />}`, not `asChild`.
- `cacheComponents` is on: don't read cookies or headers in server components without a Suspense boundary.
- `proxy.ts` is the Next 16 name for middleware. It exports `config`.
- The SSE event shape is defined in **three places** that must stay in sync: `backend/app/services/chat_service.py`, `frontend/lib/sse.ts` + `frontend/types/api.ts`, and `docs/api-specification.md`.

---

## 11. Configuration, running and deploying

### Configuration

Every variable is documented in [`.env.example`](../.env.example). The most important ones:

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | Postgres (`postgresql+psycopg://…`) |
| `GOOGLE_API_KEY`, `TAVILY_API_KEY` | Gemini, web search |
| `SECRET_KEY` | Signs CSRF tokens. Must be strong in production. |
| `GEMINI_MODEL` / `GEMINI_MODELS` | Default model / allow-list (the default must be in the list) |
| `LLM_PROVIDER=fake` | Offline scripted model, no keys needed (refused in production) |
| `CHROMA_MODE` | `persistent` / `http` / `ephemeral` |
| `STORAGE_BACKEND` | `local` / `s3` |
| `BACKEND_URL` (frontend) | Where Next.js proxies `/api/v1`. **Baked in at build time.** |

### Running locally

```bash
cp .env.example .env      # add keys, or set LLM_PROVIDER=fake
make db-up                # Postgres in Docker
make install              # uv sync + pnpm install
make migrate              # alembic upgrade head
make dev-backend          # :8000 (OpenAPI docs at /api/docs)
make dev-frontend         # :3000
```

Or run the whole stack in Docker: `docker compose up --build` (stop it with `docker compose stop`, or `make down`). After changing backend code, rebuild with `docker compose up -d --build backend`.

### Deploying

- **Frontend → Vercel** (root dir `frontend`, env `BACKEND_URL`).
- **Backend → Render** via [`render.yaml`](../render.yaml): Docker backend + managed Postgres + a persistent disk at `/data` for Chroma and uploads. Migrations run in `preDeployCommand`. Render's filesystem is wiped on deploy everywhere except the disk.
- Details: [`deployment.md`](deployment.md).

---

## 12. Testing

No test ever calls Gemini or Tavily. They use `FakeChatModel`, `HashingEmbeddings` and `FakeSearch` through `ContainerOverrides`.

| Suite | Where | Command | Needs |
|---|---|---|---|
| Backend unit | `backend/tests/unit` | `cd backend && uv run pytest tests/unit` | nothing |
| Backend integration + e2e | `backend/tests/integration`, `e2e` | `TEST_DATABASE_URL=… uv run pytest` | a throwaway Postgres DB (dropped and recreated) |
| Frontend unit | `frontend/tests/unit` | `cd frontend && pnpm test` | nothing |
| Frontend e2e | Playwright | `pnpm test:e2e` | running servers with the fake LLM |

Database tests are **skipped** (not failed) without `TEST_DATABASE_URL`, so run them before merging.

Quality gates: `make lint`, `make typecheck` (mypy `--strict`, `tsc`), `make test`, or `make check` for all three.

Good tests to read for learning:

- `tests/integration/test_chat_stream.py`: the whole streaming protocol, including stop and regenerate.
- `tests/unit/test_agent_graph.py`: the graph with the fake model, and concurrent runs isolated by context.
- `frontend/tests/unit/`: the reducer and SSE parser.

---

## 13. Reading order and exercises

### Suggested reading order (about 3 hours)

1. [`README.md`](../README.md) and [`architecture.md`](architecture.md) (15 min)
2. **The agent core** (30 min): [`agents/state.py`](../backend/app/agents/state.py) → [`agents/graph.py`](../backend/app/agents/graph.py) → [`agents/nodes/__init__.py`](../backend/app/agents/nodes/__init__.py) → [`agents/prompts.py`](../backend/app/agents/prompts.py)
3. **Streaming** (45 min, the most important file): [`services/chat_service.py`](../backend/app/services/chat_service.py), then [`endpoints/chat.py`](../backend/app/api/v1/endpoints/chat.py)
4. **Wiring** (20 min): [`main.py`](../backend/app/main.py) → [`core/container.py`](../backend/app/core/container.py) → [`api/deps.py`](../backend/app/api/deps.py)
5. **One tool end to end** (20 min): [`tools/memory.py`](../backend/app/tools/memory.py) → [`services/memory_service.py`](../backend/app/services/memory_service.py)
6. **Frontend chat** (40 min): [`lib/sse.ts`](../frontend/lib/sse.ts) → [`lib/chat-reducer.ts`](../frontend/lib/chat-reducer.ts) → [`hooks/use-chat-stream.ts`](../frontend/hooks/use-chat-stream.ts) → [`components/chat/chat-view.tsx`](../frontend/components/chat/chat-view.tsx) → [`chat-route.tsx`](../frontend/components/chat/chat-route.tsx)
7. Reference as needed: [`api-specification.md`](api-specification.md), [`database-schema.md`](database-schema.md), [`development.md`](development.md)

### Exercises (each one teaches one subsystem)

1. **Watch the protocol.** Run with `LLM_PROVIDER=fake FAKE_LLM_TOKEN_DELAY=0.05`. In the browser DevTools → Network, open the `chat/stream` request and watch the events arrive. Try `calculate 12*7` and `remember I like tea`.
2. **Press Stop mid-answer**, reload the page, and check that the message shows as stopped. Then find the code path that saved it (`_on_cancel`).
3. **Add a tool**, for example `current_time(timezone)`. Follow "New tool" in [`development.md`](development.md): builder in `tools/`, register it in `build_tools` and `TOOL_LABELS` (and the frontend copy), and mention it in the prompt. Add a unit test.
4. **Change the system prompt** and notice that old conversations pick it up immediately, because the prompt isn't stored in state.
5. **Trace a delete.** Delete a conversation with an uploaded file, and check that the message rows, the document row, the Chroma vectors and the file on disk are all gone.
6. **Break isolation on purpose (in a test).** Write a test where user B asks for user A's conversation. Confirm it returns 404, and find the repository query that enforces it.

---

## 14. Gotchas and troubleshooting

| Symptom | Cause / fix |
|---|---|
| Every chat fails with *"The assistant could not complete this response"* | Look at the backend logs for `chat_generation_failed`. In Nov 2026 the cause was **Google retiring the `gemini-2.5-*` models** (404 "no longer available to new users"). Fix: update `GEMINI_MODEL`/`GEMINI_MODELS` in `.env`, `config.py` defaults and `render.yaml`, then rebuild. The error message names the replacement model. |
| `422 Unknown model` | The requested model id isn't in `GEMINI_MODELS`. There's deliberately no fallback. |
| `403 csrf_failed` | The frontend lost its in-memory CSRF token (for example after a hard refresh before `/auth/me` returned), or a custom client didn't send `X-CSRF-Token`. |
| Frontend calls the wrong backend | `BACKEND_URL` is read at **build** time. Rebuild after changing it. |
| Stream arrives all at once instead of token by token | Something is buffering: compression, or a proxy without `X-Accel-Buffering: no`. |
| Documents stuck in "processing" | The server restarted mid-ingest. At startup they're marked `failed` after 15 minutes. Upload again. |
| Changed a model, docs or code, but Docker still behaves the old way | The image wasn't rebuilt: `docker compose up -d --build backend`. |
| Migration test fails | You changed a model without generating a migration: `make migration m="..."`. |

---

## 15. Glossary

| Term | Meaning here |
|---|---|
| **Agent** | An LLM that can call tools in a loop until it has an answer |
| **LangGraph** | The library that runs the agent as a graph of nodes with saved state |
| **Node** | One step in the graph (`chatbot`, `tools`) |
| **Checkpoint** | A saved snapshot of graph state after a step, keyed by `thread_id` |
| **Thread** | One conversation's checkpoint history (`thread_id = conversation.id`) |
| **Runtime context** | Per-run data (`AgentContext`) passed to nodes and tools, never persisted |
| **Tool call** | The model's structured request to run a tool with arguments |
| **RAG** | Retrieval-Augmented Generation: search the user's documents and give the relevant passages to the model |
| **Embedding** | A vector representing text meaning. Close vectors mean similar text. |
| **Chunk** | A ~900-character piece of a document that gets embedded |
| **Vector distance** | How different two embeddings are (smaller means more similar) |
| **SSE** | Server-Sent Events: a one-way HTTP stream of `data:` lines |
| **CSRF** | A cross-site request forgery attack. Blocked here by the HMAC token and the Origin check. |
| **Container** (backend) | The object holding all long-lived resources (not a Docker container) |
| **Optimistic update** | Showing the user's message immediately, before the server confirms it |
