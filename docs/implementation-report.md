# KayGPT 2.0 — Implementation Report

Date: 2026-11-23. Scope: the refactoring brief (phases 0–8). Starting point: commit `020e9dd`.

## Summary

The single-process FastAPI + Jinja2 app is now a monorepo with an independently deployable **FastAPI backend** (`backend/`) and **Next.js frontend** (`frontend/`). PostgreSQL holds all application data and LangGraph checkpoints. Every original capability is preserved: Gemini model selection, LangGraph tool calling, Tavily search, RAG over uploads, long-term memory, calculator, conversation history, streaming, and voice dictation. The concurrency, security and persistence defects found in the audit are fixed.

## Feature map (original → now)

| Feature | 2.0 implementation | Verified by |
|---|---|---|
| Chat + streaming | `ChatService` + `ChatStreamer`, typed SSE protocol, keep-alives | `test_chat_stream.py`, live-server e2e, Playwright |
| Model selection | `ModelService` registry from `GEMINI_MODELS`, per-run via context; unknown ids → 422 | `test_agent_graph.py`, `test_invalid_requests` |
| LangGraph graph | Same `chatbot ⇄ tools` topology, one compiled graph | `test_calculator_tool_loop`, continuity tests |
| Checkpointing | `AsyncPostgresSaver` on a shared pool | `test_postgres_checkpointer_persists_across_app_restarts` |
| Web search | `TavilySearchProvider` behind `WebSearchProvider` | `test_web_search_tool_uses_provider` (fake provider) |
| RAG + uploads | Validated upload → storage → background ingestion with status → Chroma, scoped per user and conversation | `test_documents_and_memory.py`, `test_rag_pipeline.py`, Playwright upload test |
| Memory | Postgres rows + semantic Chroma index, dedup, CRUD API + Settings UI | memory API/agent tests, Playwright memory test |
| Calculator | AST evaluator (no `eval`) | `test_calculator.py` (incl. sandbox-escape and DoS inputs) |
| History | Paginated messages, search/rename/delete conversations | `test_conversations.py`, Playwright switching test |
| Dictation | `useSpeechRecognition` hook in the composer | Manual (browser API) |
| Tool progress UI | Real `tool_start`/`tool_end` events (was regex guessing) | reducer tests, Playwright tool test |

New: accounts and sessions, CSRF, rate limits, preferences (theme, default model), document management, stop generation, regenerate, Markdown + code highlighting, copy, timestamps, mobile layout, legacy data import, vector-index rebuild script.

## Test and quality results (final run)

| Check | Result |
|---|---|
| Backend `ruff check`, `ruff format --check` | pass |
| Backend `mypy --strict app scripts` (68 files) | pass |
| Backend `pytest` with PostgreSQL 16 (unit 65 + integration 32 + live-server e2e 2) | **99 passed** |
| Frontend `eslint`, `prettier --check`, `tsc --noEmit` (strict) | pass |
| Frontend `vitest` (SSE parser, reducer, ChatView, ChatRoute, AuthForm) | **19 passed** |
| Frontend `next build` (Next 16.4.6, cacheComponents) | pass |
| Playwright e2e vs real stack: Next.js proxy, FastAPI, PostgreSQL, fake LLM (desktop + mobile) | **11 passed** |
| SSE through the Next.js rewrite | 43 separate chunks over 2.2 s (incremental, uncompressed) |
| Docker images | `kaygpt-backend` (1.05 GB, non-root uid 1001) and `kaygpt-frontend` (326 MB, standalone) build |
| `docker compose up` (offline mode, `LLM_PROVIDER=fake`) | all 3 services healthy; migrations run on start; chat streams through the frontend container; conversations, checkpoints and the indexed document survive a backend restart |

Automated tests never call Gemini or Tavily (fake chat model, hashing embeddings, fake search provider).

## Security review (Phase 8 checklist)

| Item | Status |
|---|---|
| No SQLite production dependency | ✅ `DATABASE_URL` must be PostgreSQL (validated at startup); legacy SQLite only read by the optional import script (stdlib) |
| No hardcoded credentials | ✅ scanned; dev-only placeholder secret is rejected in production |
| No global conversation state | ✅ runtime context; concurrency regression tests (20 parallel runs; 4 parallel users with memory tools) |
| No cross-user leakage | ✅ ownership checks on every query and vector search; tests for conversations, messages, documents, memories, chat hijack, uploads into others' chats |
| Streaming | ✅ protocol, errors (no internals), cancellation (partial saved as `stopped`), dangling tool-call repair, keep-alives |
| Every endpoint tested | ✅ all 23 routes covered by integration tests |
| Environment variables documented | ✅ `.env.example`, deployment docs |
| Migrations | ✅ Alembic initial revision; drift test; autogenerate ignores LangGraph tables |
| Deployment configuration | ✅ Dockerfiles, Compose, `render.yaml`, Vercel instructions, CI workflow |

Fixed during review: rate limits for chat/upload moved from per-IP (spoofable through `X-Forwarded-For` when calling the API directly) to per-user. Stale session cookies are cleared on 401, which prevents a redirect loop between the frontend guard and the client shell. Managed `postgres://` URLs are normalized to psycopg 3. Alembic no longer offers to drop LangGraph tables.

## Decisions and assumptions

- **Auth**: built from scratch (none existed). Server-side sessions plus a session-bound CSRF token were chosen over JWTs for revocable logout and no tokens in JS. The same-origin proxy keeps cookies first-party between Vercel and Render.
- **Gemini 1.5 removed** from the default model list (retired upstream). The list is configurable.
- **Memory relevance** uses the existing Chroma + Gemini embeddings instead of adding pgvector. Recall returns the top-k matches within a configurable cosine distance (`MEMORY_RECALL_MAX_DISTANCE=0.8`). That threshold is tuned for Gemini embeddings by assumption; adjust after observing real data.
- **Documents** keep the original per-conversation scope; uploads from the Documents panel are user-wide.
- **Message persistence**: the UI transcript (`messages`) and agent memory (checkpoints) stay separate, as before, but are now deleted together.
- **Next.js 16 defaults kept** (`cacheComponents`, Turbopack); the chat shell is client-rendered inside Suspense.
- **shadcn/ui 4** generated the Base UI variant, plus its `cn` package (verified: published by the shadcn maintainers).
- **Local dev constraint**: newer `cryptography` and `onnxruntime` ship no Intel-macOS wheels, so `uv.lock` targets versions with wheels for Linux x86_64 and both macOS architectures.

## What was not verified (needs the owner)

1. **Real Gemini and Tavily calls.** No API keys were available in this environment, so every AI path ran with fakes. Before release, run once with real keys: a normal question, a time-sensitive question (web search), an uploaded PDF, "remember"/"recall", and each selectable model. The streaming code handles Gemini's list-of-blocks message content and drops non-text blocks, but this has not been exercised against live Gemini responses.
2. **Deployments.** Nothing was deployed to Vercel or Render. Follow docs/deployment.md, then its post-deploy checklist. In particular, check long-running SSE and 20 MB uploads through Vercel's external-rewrite proxy.
3. **Docker Compose with real keys.** The stack was verified offline (`LLM_PROVIDER=fake`). Note: npm downloads inside Docker were unreliable on the build machine (ECONNRESET), and one frontend build needed a retry.

## Open items and recommendations

- **Git history contains personal data.** The previous commits include `uploads/…Boktiar_Ahmed_Bappy_CV.pdf.pdf` (a third party's CV), the SQLite chat/memory databases and the Chroma store. They are now untracked (files left on disk) and ignored, but remain in history and on GitHub. Purging requires rewriting history (`git filter-repo`) and a force-push, and contributors would need to re-clone. **Owner decision required.**
- `LICENSE`: the Apache 2.0 appendix still has the `[yyyy] [name of copyright owner]` placeholder (boilerplate; fill in if you want a NOTICE).
- Rate limiting and background ingestion are in-process. For more than one backend instance: Redis-backed limits, a job queue for ingestion, `CHROMA_MODE=http`, `STORAGE_BACKEND=s3`.
- Login is rate-limited per IP only. Consider adding per-account lockout and email verification/password reset (no email service exists yet).
- Old uploads (one CV) are not migrated: the old index has no ownership information.

## Files

New: `backend/` (app, alembic, tests, scripts, Dockerfile), `frontend/` (Next.js app, tests, Dockerfile), `docker-compose.yml`, `docker-compose.dev.yml`, `docker/`, `render.yaml`, `.github/workflows/ci.yml`, `Makefile`, `.env.example`, `.dockerignore`, `docs/*`.
Rewritten: `README.md`, `CLAUDE.md`, `.gitignore`.
Removed (superseded, still in git history): `app.py`, `agent.py`, `tools.py`, `rag.py`, `database.py`, `test.py`, `requirements.txt`, `templates/index.html`.
Untracked (still on disk): `data/`, `chroma_db/`, `uploads/`.
