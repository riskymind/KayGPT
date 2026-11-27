# KayGPT

An agentic AI chat assistant. KayGPT answers questions with Google Gemini, decides on its own when to search the web, read your uploaded documents, remember facts about you, or use a calculator, and streams its answers token by token.

## Features

- **Streaming chat** with Markdown, syntax-highlighted code, copy, regenerate, stop generation and timestamps
- **Multiple Gemini models**, selectable per message, with a saved default
- **Agent tools** (LangGraph): web search (Tavily), document search (RAG over ChromaDB), long-term memory, calculator, with live tool-progress indicators
- **Documents**: upload PDF, DOCX, TXT, Markdown, Python or CSV, per chat or for all chats, with processing status
- **Long-term memory**: per user, semantic recall, duplicate suppression, manageable in Settings
- **Conversations**: history, search, rename, delete; context persists across restarts
- **Accounts**: registration and login with secure server-side sessions; every user's data is isolated
- **Voice dictation** in the composer (browsers with the Web Speech API)
- Responsive layout with dark/light/system theme

## Architecture

```text
frontend/  Next.js 16 (App Router, TypeScript, Tailwind, shadcn/ui, TanStack Query)  → Vercel
backend/   FastAPI + LangGraph + LangChain (Gemini, Tavily) + ChromaDB                  → Render
           PostgreSQL: users, conversations, messages, memories, documents, LangGraph checkpoints
```
The browser talks only to the Next.js origin, which proxies `/api/v1/*` to FastAPI (first-party cookies). See [docs/architecture.md](docs/architecture.md).

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript (strict), Tailwind CSS 4, shadcn/ui (Base UI), Lucide, TanStack Query, React Hook Form + Zod, react-markdown |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async, psycopg 3), Alembic |
| AI | LangGraph 1.x, LangChain 1.x, Google Gemini (chat + embeddings), Tavily, ChromaDB |
| Persistence | PostgreSQL (app data + `langgraph-checkpoint-postgres`), Chroma, local disk or S3-compatible storage |
| Quality | pytest, Ruff, mypy (strict), Vitest, React Testing Library, Playwright, ESLint, Prettier |

## Quick start (Docker)

Requirements: Docker with Compose v2, a [Google AI Studio](https://aistudio.google.com/) API key, and a [Tavily](https://tavily.com/) API key.

```bash
cp .env.example .env        # set GOOGLE_API_KEY and TAVILY_API_KEY
docker compose up --build
```
Open http://localhost:3000 and create an account. Data persists in Docker volumes (`docker compose down -v` deletes it).

## Local development

Prerequisites: Python 3.11–3.13 with [uv](https://docs.astral.sh/uv/), Node.js 20.9+ with pnpm 9, PostgreSQL 14+ (or Docker).

```bash
cp .env.example .env
make db-up          # PostgreSQL in Docker
make install        # backend + frontend dependencies
make migrate
make dev-backend    # http://localhost:8000  (API docs: /api/docs)
make dev-frontend   # http://localhost:3000
```
No API keys? Set `LLM_PROVIDER=fake` for a deterministic offline model (see [docs/development.md](docs/development.md)).

## Environment variables

All variables are documented in [.env.example](.env.example). The essentials:

| Variable | Where | Purpose |
|---|---|---|
| `DATABASE_URL` | backend | PostgreSQL URL (`postgres://` URLs are accepted) |
| `GOOGLE_API_KEY`, `GEMINI_MODEL`, `GEMINI_MODELS` | backend | Gemini access, default model, selectable models |
| `TAVILY_API_KEY` | backend | Web search |
| `SECRET_KEY` | backend | Signs CSRF tokens; required in production |
| `FRONTEND_URL` / `CORS_ORIGINS` | backend | Allowed browser origins |
| `CHROMA_*`, `STORAGE_BACKEND`, `UPLOAD_DIR`, `S3_*` | backend | Vector index and file storage |
| `BACKEND_URL` | frontend (build time) | Where Next.js proxies `/api/v1/*` |

## Testing

```bash
make check                     # lint + typecheck + unit/integration tests (no API keys needed)
cd frontend && pnpm test:e2e   # Playwright end-to-end (see docs/development.md)
```
Backend database tests need `TEST_DATABASE_URL`. LLM and web search are faked in every automated test.

## Deployment

- **Frontend → Vercel** (root directory `frontend`, env `BACKEND_URL`)
- **Backend + PostgreSQL → Render** via the [`render.yaml`](render.yaml) Blueprint (persistent disk for the vector index and uploads)
- **Everything → Docker Compose**

Step-by-step instructions, storage options and a post-deploy checklist: [docs/deployment.md](docs/deployment.md).

## Documentation

- [Architecture](docs/architecture.md) · [API specification](docs/api-specification.md) · [Database schema](docs/database-schema.md)
- [Development](docs/development.md) · [Deployment](docs/deployment.md)
- [Audit report](docs/audit-report.md) · [Refactoring roadmap](docs/refactoring-roadmap.md) · [Implementation report](docs/implementation-report.md)

## License

Apache License 2.0. See [LICENSE](LICENSE).
