# DigiTwin - developer entry points.
#
# Two runtimes: a Python service in services/twin-core (uv) and a React
# console in apps/console (npm). `make dev` runs both.

SHELL := /bin/bash
BACKEND := services/twin-core
CONSOLE := apps/console

.DEFAULT_GOAL := help
.PHONY: help install dev backend console build test lint fmt check clean docker screenshots

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install both runtimes
	cd $(BACKEND) && uv sync --extra dev
	cd $(CONSOLE) && npm install

backend: ## Run twin-core on :8000
	cd $(BACKEND) && uv run uvicorn app.main:app --reload --port 8000

console: ## Run the console on :5173 (proxies /api to :8000)
	cd $(CONSOLE) && npm run dev

dev: ## Run both, streaming logs together
	@trap 'kill 0' EXIT INT TERM; \
	( cd $(BACKEND) && uv run uvicorn app.main:app --reload --port 8000 2>&1 | sed 's/^/[twin-core] /' ) & \
	( cd $(CONSOLE) && npm run dev 2>&1 | sed 's/^/[console]   /' ) & \
	wait

build: ## Production build of the console
	cd $(CONSOLE) && npm run build

test: ## Run both test suites
	cd $(BACKEND) && uv run pytest -q
	cd $(CONSOLE) && npm run test

lint: ## Lint and typecheck both runtimes
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check .
	uv run --project $(BACKEND) ruff check .
	cd $(CONSOLE) && npm run lint

fmt: ## Auto-format the backend
	cd $(BACKEND) && uv run ruff format . && uv run ruff check --fix .

check: lint test ## Everything CI runs

screenshots: ## Regenerate the doc screenshots (needs the stack running)
	cd $(BACKEND) && uv run python ../../scripts/screenshots.py --out ../../docs/images

docker: ## Build and run the full stack
	docker compose up --build

clean: ## Remove build artefacts and virtualenvs
	rm -rf $(BACKEND)/.venv $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache
	rm -rf $(CONSOLE)/node_modules $(CONSOLE)/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
