# KayGPT frontend

Next.js 16 (App Router) UI for KayGPT. See the [root README](../README.md) and [docs/development.md](../docs/development.md).

```bash
pnpm install
BACKEND_URL=http://localhost:8000 pnpm dev   # http://localhost:3000
pnpm lint && pnpm typecheck && pnpm test     # quality gates
pnpm test:e2e                                # Playwright (needs running backend + frontend)
```
