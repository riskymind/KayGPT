# KayGPT developer commands. Run `make help`.
SHELL := /bin/bash
BACKEND := cd backend &&
FRONTEND := cd frontend &&

.PHONY: help install db-up db-down migrate migration dev-backend dev-frontend \
        lint typecheck test test-backend test-frontend e2e check up down

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## Install backend (uv) and frontend (pnpm) dependencies
	$(BACKEND) uv sync
	$(FRONTEND) pnpm install

db-up: ## Start PostgreSQL in Docker for local development
	docker compose -f docker-compose.dev.yml up -d

db-down: ## Stop the development PostgreSQL
	docker compose -f docker-compose.dev.yml down

migrate: ## Apply database migrations
	$(BACKEND) uv run alembic upgrade head

migration: ## Create a migration from model changes: make migration m="add foo"
	$(BACKEND) uv run alembic revision --autogenerate -m "$(m)" && uv run ruff format alembic/versions

dev-backend: ## Run FastAPI with reload on :8000
	$(BACKEND) uv run uvicorn app.main:create_app --factory --reload --port 8000

dev-frontend: ## Run Next.js dev server on :3000
	$(FRONTEND) pnpm dev

lint: ## Lint and format-check both apps
	$(BACKEND) uv run ruff check . && uv run ruff format --check .
	$(FRONTEND) pnpm lint && pnpm format:check

typecheck: ## mypy (strict) and tsc
	$(BACKEND) uv run mypy app scripts
	$(FRONTEND) pnpm typecheck

test-backend: ## pytest (needs TEST_DATABASE_URL for database tests)
	$(BACKEND) uv run pytest

test-frontend: ## Vitest unit/component tests
	$(FRONTEND) pnpm test

test: test-backend test-frontend ## All automated tests (no API keys needed)

e2e: ## Playwright against running servers (see docs/development.md)
	$(FRONTEND) pnpm test:e2e

check: lint typecheck test ## Everything CI runs

up: ## Build and start the full stack in Docker
	docker compose up --build

down: ## Stop the Docker stack (volumes are kept)
	docker compose down
