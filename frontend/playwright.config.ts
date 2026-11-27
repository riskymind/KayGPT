import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the real stack: Next.js + FastAPI + PostgreSQL, with the backend's
 * deterministic fake LLM (LLM_PROVIDER=fake) so no API keys are needed.
 *
 * Locally: start both servers yourself (see docs/development.md) or let `webServer` start them.
 * Required env for auto-start: E2E_DATABASE_URL (a disposable PostgreSQL database).
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const databaseUrl = process.env.E2E_DATABASE_URL;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // PW_CHANNEL=chrome uses an installed Google Chrome instead of the bundled Chromium.
    ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}),
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, grepInvert: /@mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: databaseUrl
    ? [
        {
          command:
            "uv run alembic upgrade head && uv run uvicorn app.main:create_app --factory --port 8000",
          cwd: "../backend",
          url: "http://localhost:8000/api/v1/health",
          reuseExistingServer: true,
          timeout: 120_000,
          env: {
            DATABASE_URL: databaseUrl,
            APP_ENV: "test",
            LLM_PROVIDER: "fake",
            FAKE_LLM_TOKEN_DELAY: "0.05",
            SECRET_KEY: "e2e-secret-key-e2e-secret-key-0123456789",
            FRONTEND_URL: baseURL,
            CHROMA_MODE: "ephemeral",
            UPLOAD_DIR: "./.e2e-uploads",
            RATE_LIMIT_AUTH_PER_MINUTE: "1000",
          },
        },
        {
          command: "pnpm build && pnpm start",
          url: baseURL,
          reuseExistingServer: true,
          timeout: 300_000,
          env: { BACKEND_URL: "http://localhost:8000" },
        },
      ]
    : undefined,
});
