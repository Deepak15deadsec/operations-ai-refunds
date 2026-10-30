SHELL := /bin/bash
-include .env
export

COMPOSE ?= docker compose
TEST_PG_PORT ?= 55432
TEST_DATABASE_URL ?= postgresql+psycopg://app:local_only@localhost:$(TEST_PG_PORT)/operations_test

.PHONY: help up down logs migrate seed test test-db lint typecheck eval token e2e clean

help:
	@echo "up        build and start the full stack (migrations + seed run automatically)"
	@echo "migrate   run alembic upgrade head + checkpointer setup in the stack"
	@echo "seed      reset demo fixtures"
	@echo "test      backend + MCP tests against a throwaway Postgres (no LLM key needed)"
	@echo "lint      ruff;  typecheck: mypy"
	@echo "eval      run the 37-scenario evaluation and write docs/evaluation-report.md"
	@echo "token     print a dev access token (USER_NAME=supervisor PASS=supervisor-demo)"
	@echo "e2e       Playwright E2E against the running stack"

up:
	$(COMPOSE) up --build -d
	@echo "Web: http://localhost:$${WEB_PORT:-3000}  API: http://localhost:$${API_PORT:-8000}/docs  Keycloak: http://localhost:$${KEYCLOAK_PORT:-8080}"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api worker mcp-operations

migrate:
	$(COMPOSE) run --rm -e SEED_DEMO=false migrate

seed:
	$(COMPOSE) run --rm migrate python -m scripts.seed

test-db:
	@docker inspect opsai-test-pg >/dev/null 2>&1 || docker run -d --name opsai-test-pg \
		-e POSTGRES_USER=app -e POSTGRES_PASSWORD=local_only -e POSTGRES_DB=operations_test \
		-p 127.0.0.1:$(TEST_PG_PORT):5432 postgres:16-alpine >/dev/null
	@docker start opsai-test-pg >/dev/null
	@until docker exec opsai-test-pg pg_isready -U app -d operations_test >/dev/null 2>&1; do sleep 1; done

test: test-db
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest

lint:
	uv run ruff check backend mcp_servers evaluations

typecheck:
	uv run mypy backend/app mcp_servers/operations/operations_mcp

eval: test-db
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) uv run python evaluations/run_evals.py

token:
	@curl -s -X POST "http://localhost:$${KEYCLOAK_PORT:-8080}/realms/operations-demo/protocol/openid-connect/token" \
		-d grant_type=password -d client_id=operations-cli \
		-d username=$${USER_NAME:-supervisor} -d password=$${PASS:-supervisor-demo} | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'

e2e:
	cd frontend && E2E_BASE_URL=http://localhost:$${WEB_PORT:-3000} npx playwright test

clean:
	$(COMPOSE) down -v
	-docker rm -f opsai-test-pg
