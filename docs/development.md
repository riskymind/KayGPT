# Developing KayGPT

## Prerequisites
- Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/)
- Node.js 20.9+ and pnpm 9 (`corepack enable`)
- PostgreSQL 14+ (Docker: `make db-up`, or a local install)

## First-time setup
```bash
cp .env.example .env                 # GOOGLE_API_KEY, TAVILY_API_KEY; adjust DATABASE_URL
make db-up                           # Postgres on localhost:5432 (+ kaygpt_test database)
make install                         # uv sync + pnpm install
make migrate                         # alembic upgrade head
```
Run the two servers in separate terminals:
```bash
make dev-backend                     # http://localhost:8000 (OpenAPI docs at /api/docs)
make dev-frontend                    # http://localhost:3000
```
The backend reads `.env` from the repo root (or `backend/.env`). The frontend dev server proxies `/api/v1/*` to `BACKEND_URL` (default `http://localhost:8000`).

### Working without API keys
Set `LLM_PROVIDER=fake` in `.env`. The backend then uses a deterministic fake model and offline embeddings:
- `calculate 2+2`, `remember <fact>`, `recall <query>`, `search docs <query>`, `search web <query>` trigger the matching tool.
- Anything else is echoed back (`Echo: …`), streamed word by word. `FAKE_LLM_TOKEN_DELAY=0.05` slows the stream (useful for testing Stop).
- Without `TAVILY_API_KEY`, `web_search` answers "Web search is not configured on this server."

`LLM_PROVIDER=fake` is refused when `APP_ENV=production`.

## Tests

| Suite | Command | Needs |
|---|---|---|
| Backend unit | `cd backend && uv run pytest tests/unit` | nothing |
| Backend integration + e2e | `TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/kaygpt_test uv run pytest` | PostgreSQL (database is dropped/recreated and migrated) |
| Frontend unit/component | `cd frontend && pnpm test` | nothing |
| Frontend e2e (Playwright) | `cd frontend && pnpm exec playwright install chromium && pnpm test:e2e` | running backend (fake LLM) + frontend, or `E2E_DATABASE_URL` so Playwright starts them |

No test calls Gemini or Tavily. Database-backed tests are skipped (not failed) when `TEST_DATABASE_URL` is unset, so run them with it before merging.

Playwright against servers you started yourself:
```bash
# terminal 1 (backend, fake LLM)
cd backend && LLM_PROVIDER=fake FAKE_LLM_TOKEN_DELAY=0.05 RATE_LIMIT_AUTH_PER_MINUTE=1000 \
  uv run uvicorn app.main:create_app --factory --port 8000
# terminal 2
cd frontend && pnpm build && pnpm start
# terminal 3
cd frontend && pnpm test:e2e
```

## Quality gates
```bash
make lint        # ruff check + ruff format --check, eslint + prettier --check
make typecheck   # mypy --strict (backend), tsc --noEmit (frontend, strict)
make test        # pytest + vitest
make check       # all of the above
```

## Common tasks
- **New DB column/table**: edit `backend/app/models/…`, then `make migration m="add x"`, review the generated file, `make migrate`. `test_migrations_match_models` catches drift.
- **New tool**: add a builder in `backend/app/tools/`, read user/conversation from `runtime: ToolRuntime[AgentContext]` (never globals), register it in `tools/__init__.py` (`build_tools`, `TOOL_LABELS`), and mention it in `agents/prompts.py`.
- **New model provider**: implement `ChatModelProvider.create()` in `backend/app/llm/providers.py` and register it in `ModelService.from_settings`.
- **New endpoint**: schema in `app/schemas`, logic in a service, thin handler in `app/api/v1/endpoints`, route in `router.py`; mirror types in `frontend/types/api.ts` and add a function in `frontend/services/index.ts`; document it in `docs/api-specification.md`.
- **New shadcn component**: `cd frontend && pnpm dlx shadcn@latest add <name>` (this project uses the Base UI variant: compose with `render={<Button />}`, not `asChild`).

## Importing pre-2.0 data
```bash
cd backend
uv run python -m scripts.import_legacy_sqlite --sqlite ../data/chatbot_memory.db --email you@example.com --dry-run
uv run python -m scripts.import_legacy_sqlite --sqlite ../data/chatbot_memory.db --email you@example.com
uv run python -m scripts.reindex --memories
```
Register the target account first. Old uploads must be re-uploaded (the old index has no owner information).
