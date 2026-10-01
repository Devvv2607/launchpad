# Launchpad developer commands. On Windows, run from Git Bash or WSL with `make` installed.
SHELL := bash
PY ?= api/.venv/bin/python
ifeq ($(OS),Windows_NT)
PY := api/.venv/Scripts/python
endif

.PHONY: help setup keys up down logs migrate migration dev-api dev-worker dev-web \
        test lint fmt typecheck gen-api check

help:  ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup:  ## Create the Python venv and install API, worker and web dependencies
	python3.11 -m venv api/.venv || py -3.11 -m venv api/.venv
	$(PY) -m pip install -e "./api[dev]" -e ./worker
	cd web && npm ci

keys:  ## Print fresh secrets for .env
	@echo "JWT_SECRET=$$($(PY) -c 'import secrets;print(secrets.token_urlsafe(48))')"
	@echo "TOKEN_ENCRYPTION_KEYS=$$($(PY) -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"

up:  ## Build and start the full stack in Docker
	docker compose up --build -d
	@echo "Web: http://localhost:3000  API docs: http://localhost:8000/docs"

down:  ## Stop the stack
	docker compose down

logs:  ## Tail logs from all services
	docker compose logs -f --tail=100

migrate:  ## Apply database migrations
	cd api && ../$(PY) -m alembic upgrade head

migration:  ## Autogenerate a migration: make migration m="add foo"
	cd api && ../$(PY) -m alembic revision --autogenerate -m "$(m)"

dev-api:  ## Run the API with reload (needs Postgres + Redis)
	cd api && ../$(PY) -m uvicorn launchpad.main:app --reload --port 8000

dev-worker:  ## Run the background worker
	cd api && ../$(PY) -m arq launchpad_worker.main.WorkerSettings

dev-web:  ## Run the web app with hot reload
	cd web && npm run dev

test:  ## Run backend tests (set TEST_DATABASE_URL to a disposable database)
	cd api && ../$(PY) -m pytest
	cd worker && ../$(PY) -m pytest

lint:  ## Lint and format-check everything
	cd api && ../$(PY) -m ruff check . && ../$(PY) -m ruff format --check .
	cd worker && ../$(PY) -m ruff check . && ../$(PY) -m ruff format --check .
	cd web && npm run -s lint && npm run -s format:check

fmt:  ## Auto-format everything
	cd api && ../$(PY) -m ruff check --fix . && ../$(PY) -m ruff format .
	cd worker && ../$(PY) -m ruff check --fix . && ../$(PY) -m ruff format .
	cd web && npm run -s format

typecheck:  ## mypy (strict) + tsc
	cd api && ../$(PY) -m mypy
	cd worker && ../$(PY) -m mypy
	cd web && npm run -s typecheck

gen-api:  ## Regenerate the OpenAPI spec and the typed TS client
	cd api && ../$(PY) -m launchpad.openapi > ../web/openapi.json
	cd web && npm run -s gen:api

check: lint typecheck test  ## Everything CI runs
