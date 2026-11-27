# KayGPT — Phase 0 Repository Audit

Audited commit: `020e9dd` (branch `main`). Audit date: 2026-11-23.

## 1. Inventory

| File | Lines | Role |
|---|---|---|
| `app.py` | 303 | FastAPI app: Jinja2 page, `/conversations`, `/history/{thread_id}`, `/upload`, `/chat/stream` (SSE) |
| `agent.py` | 138 | LangGraph `chatbot ⇄ tools` graph, Gemini model allow-list, system prompt, per-model graph cache, `SqliteSaver` |
| `tools.py` | 103 | `calculator`, `search_uploaded_documents`, `remember_this`, `recall_memory`, `TavilySearch`; global `CURRENT_THREAD_ID` |
| `rag.py` | 113 | Text extraction (pdf/docx/txt/md/py/csv), chunking (900/150), Chroma store, Gemini embeddings |
| `database.py` | 182 | SQLAlchemy (SQLite) tables `conversations`, `chat_messages`, `long_term_memory` + CRUD helpers |
| `templates/index.html` | 1167 | Single-page UI with inline CSS/JS, manual SSE parsing, dictation, model picker |
| `test.py` | 28 | Manual smoke script that calls Gemini (not an automated test) |
| `requirements.txt` | 19 | Pinned deps; `certifi` missing |
| `LICENSE` | 201 | Apache 2.0, copyright line still the `[yyyy] [name of copyright owner]` placeholder |
| `data/*.sqlite`, `data/*.db`, `chroma_db/**`, `uploads/*.pdf` | — | **Runtime data committed to git** |

No README, Dockerfile, CI workflow, tests, lint config or `.env.example` exist. CLAUDE.md mentions a README and an ECR/EC2 deploy that are not in the tree.

## 2. Existing features and where they go

| # | Feature | Current implementation | Target location |
|---|---|---|---|
| 1 | AI conversations | `/chat/stream` + LangGraph | `api/v1/endpoints/chat.py` → `services/chat_service.py` → `agents/` |
| 2 | Multiple Gemini models | `ALLOWED_MODELS` set + `<select>` | `services/model_service.py` (provider registry), `GET /api/v1/models` |
| 3 | LangGraph orchestration | `StateGraph(MessagesState)`, `ToolNode`, `tools_condition` | `agents/graph.py`, `agents/nodes/` (same topology) |
| 4 | Tool calling | `llm.bind_tools(tools)` | Same, tools in `tools/`, context via LangGraph runtime |
| 5 | Web search | `TavilySearch` built at import time | `tools/web_search.py` wrapping a replaceable `WebSearchProvider` |
| 6 | RAG | Chroma + metadata filter `thread_id` | `rag/` pipeline, filter by `user_id` **and** `conversation_id` |
| 7 | Document upload | `POST /upload`, synchronous ingestion | `POST /api/v1/documents/upload`, background ingestion with status |
| 8 | Conversation history | SQLite tables, `/conversations`, `/history` | Postgres `conversations`/`messages`, paginated endpoints |
| 9 | Long-term memory | SQLite `long_term_memory` per thread | Postgres per user, semantic retrieval, dedup, CRUD API |
| 10 | Calculator | `eval()` with empty builtins | AST-based safe evaluator |
| 11 | Streaming | SSE `{"token"}` / `{"done"}` / `{"error"}` | Typed event protocol (`docs/api-specification.md`) |
| 12 | Voice dictation (UI only) | Web Speech API | Kept in the Next.js chat input (not listed in the brief; preserved anyway) |
| 13 | Tool progress indicator (UI only) | **Regex guess** of which tool will run | Replaced by real `tool_start`/`tool_end` events from the graph |

## 3. Bugs and correctness problems

1. **Cross-request context leak (critical).** `tools.CURRENT_THREAD_ID` is a module global set per request (`app.py:242`). Two concurrent requests overwrite each other, so user A's `search_uploaded_documents`, `remember_this` and `recall_memory` can read/write user B's thread. This is a data-isolation bug, not just a style issue.
2. **Blocking event loop.** `chat_stream` is `async def` but returns a *sync* generator that calls `agent.stream(...)`; Starlette runs it in a threadpool, which is fine, but `upload_document` (async) runs PDF parsing and embedding calls synchronously on the event loop, stalling every other request during ingestion.
3. **Shared SQLite connection across threads.** `agent.py:115` opens one `sqlite3` connection with `check_same_thread=False` per model and shares it across the threadpool. `SqliteSaver` serializes with a lock, but each model gets its *own* connection to the same file, so writes contend.
4. **Recall ignores the query.** `database.search_memory` returns the newest 20 rows for the thread regardless of `query`.
5. **Memory is per-thread, not per-user.** "Long-term" memory saved in one chat is invisible in a new chat (new `thread_id`), which defeats its purpose.
6. **Duplicate memories.** No dedup; "remember X" twice stores two rows.
7. **Unvalidated model selection silently falls back.** Unknown model → default without telling the client.
8. **Deprecated models.** `gemini-1.5-flash`/`gemini-1.5-pro` are retired by Google; selecting them would error at inference time.
9. **Upload filename handling.** Only spaces are replaced; `file.filename` can contain `../` or path separators → path traversal in `uploads/{uuid}_{name}` (partially mitigated by the uuid prefix but `uuid_../../x` still escapes `uploads/`). File name also gets a double extension (`.pdf.pdf` seen in `uploads/`).
10. **No upload size limit.** `await file.read()` loads the whole body into memory.
11. **Failed ingestion leaves orphan files** in `uploads/` and the conversation title becomes "Uploaded document".
12. **Partial answers lost / broken state on disconnect.** If the client disconnects during tool execution, the checkpoint can end on an `AIMessage` with `tool_calls` and no `ToolMessage`; Gemini then rejects the next turn for that thread.
13. **Errors leak internals.** `str(e)` from any exception (including provider errors that can contain request details) is sent to the browser for both upload and streaming.
14. **`datetime.utcnow()`** is deprecated (3.12) and produces naive timestamps.
15. **`declarative_base()` from `sqlalchemy.orm` + `Column`** is the legacy 1.x style; not wrong but not 2.x typed mappings.
16. **CLAUDE.md drift:** README/Docker/CI referenced but missing; `GOOGLE_MODEL` vs `GEMINI_MODEL`.
17. **Branding inconsistency:** UI says "BappyGPT" and suggests "Remember that my channel name is dswithbappy" (leftover from the upstream tutorial), while the product is KayGPT.
18. `test.py` imports `init_db` twice and only prints output; it cannot fail.

## 4. Security findings

| Severity | Finding |
|---|---|
| Critical | **No authentication or authorization.** Anyone can list every conversation (`GET /conversations`) and read any history by thread id. |
| Critical | **Personal data committed to git:** `uploads/…_Boktiar_Ahmed_Bappy_CV.pdf.pdf` (a third party's CV), plus the SQLite chat/memory DBs and Chroma store containing its embedded text. Removing them from the index is safe; purging history requires a force-push and **needs owner approval**. |
| High | Calculator uses `eval`. Empty `__builtins__` is not a sandbox: attribute walks (`().__class__.__mro__…`) reach arbitrary classes, and `9**9**9**9` hangs the worker (DoS). The input is model-generated from user text, i.e. attacker-controllable via prompt. |
| High | Cross-thread data leak via global thread id (see bug 1). |
| High | Path traversal / unbounded upload (bugs 9, 10); no content sniffing (any bytes named `.pdf` are parsed). |
| Medium | No CORS policy, CSRF protection, or rate limiting. Model calls are cost-bearing; an open endpoint is a billing risk. |
| Medium | Raw exception text returned to clients. |
| Low | `reload=True` hard-coded in the entry point; would run the reloader in production. |
| Low | LICENSE copyright placeholder not filled in (Apache 2.0 appendix boilerplate; left as is — the owner should fill it). |

## 5. Deprecated / outdated APIs

- `langgraph.prebuilt.ToolNode`/`tools_condition` are still supported in LangGraph 1.x; keep them. Thread context should use LangGraph **runtime context** (`context_schema` + `ToolRuntime`) instead of globals.
- `ChatGoogleGenerativeAI(streaming=True)`: the flag is unnecessary in `stream_mode="messages"`; harmless.
- `datetime.utcnow`, SQLAlchemy `declarative_base` legacy style (see above).
- Gemini 1.5 model ids are retired.

## 6. Architectural problems

- Import-time side effects (API clients, DB engines, `mkdir`, `load_dotenv`, `os.environ` mutation) make the code impossible to import in tests without real keys and network.
- Two separate SQLite stores + local Chroma + local uploads: all four are lost on ephemeral hosts (Render, containers without volumes).
- Agent graph compiled per model with its own checkpointer connection; model choice should be a runtime parameter of one graph.
- No layering: route handlers do validation, persistence, file I/O and orchestration.
- No users → no ownership model for conversations, documents or memories.
- Frontend is a 1,167-line HTML file; tool indicator is guesswork; no markdown rendering, so code blocks render as plain text.

## 7. Existing data

Local SQLite contains 3 conversations, 19 messages, 3 memories and checkpoints for 4 threads. None of it has an owner. A one-off import script (`backend/scripts/import_legacy_sqlite.py`) will copy conversations, messages and memories into Postgres under a user chosen by the operator and seed the LangGraph checkpoint from the message history. Running it is optional and never deletes the source files.

## 8. Migration risks

| Risk | Mitigation |
|---|---|
| Render/Vercel are different sites → third-party cookies blocked by Safari/Chrome | Browser talks only to the Next.js origin; Next.js rewrites `/api/v1/*` to the backend, so auth cookies are first-party. Cross-origin mode documented as fallback. |
| Vercel external-rewrite limits (timeouts/body size) for long SSE streams and 20 MB uploads | Documented; heartbeats every 15 s keep streams alive; direct cross-origin mode configurable. To verify on first real deploy. |
| Chroma and uploads on ephemeral disk | Storage abstraction (local / S3-compatible) and Chroma mode (embedded on persistent disk / HTTP server). Render blueprint uses a persistent disk. |
| LangGraph Postgres checkpointer needs `setup()` and an autocommit pool | Run `setup()` once at startup inside the app lifespan; one shared `AsyncConnectionPool`. |
| Retiring old SQLite data | Import script; originals kept on disk, removed only from git index. |
| Tests needing Gemini/Tavily | Fake chat model and fake search provider injected through the same factories used in production. |
| Gemini model ids change over time | Allowed models configurable via `GEMINI_MODELS` env var. |
