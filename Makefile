# Developer entry points. The full stack requires Docker Compose; the test
# targets that need PostgreSQL, Redis, OPA or Vault use testcontainers.
COMPOSE := docker compose -f deploy/compose/compose.yml
API_PY := python -m
PY := python

.PHONY: help up down logs secrets db-upgrade seed lint test test-contract test-security test-e2e audit-verify check

help:
	@echo "up             start the development stack"
	@echo "down           stop the development stack"
	@echo "secrets        generate the development secret fixtures (git-ignored)"
	@echo "db-upgrade     apply database migrations"
	@echo "seed           seed roles, demo organisation and demo accounts"
	@echo "lint           ruff + mypy + eslint + tsc"
	@echo "test           unit and integration tests"
	@echo "test-contract  openapi conformance tests"
	@echo "test-security  permission matrix, deny-by-default, fail-closed"
	@echo "test-e2e       playwright end-to-end tests"
	@echo "audit-verify   recompute the audit hash chain"

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

secrets:
	$(PY) deploy/compose/generate_dev_secrets.py

db-upgrade:
	cd apps/api && $(API_PY) alembic upgrade head

seed:
	cd apps/api && $(API_PY) gov.api.infrastructure.seed

lint:
	$(API_PY) ruff check apps services
	MYPYPATH=apps/api/src $(API_PY) mypy apps/api/src
	MYPYPATH=services/gateway/src $(API_PY) mypy services/gateway/src
	MYPYPATH=services/runner/src $(API_PY) mypy services/runner/src
	MYPYPATH=services/worker/src $(API_PY) mypy services/worker/src
	$(API_PY) ruff check --select I apps services
	cd apps/web && npm run lint

test:
	cd apps/api && $(API_PY) pytest -q

test-contract:
	cd apps/api && $(API_PY) pytest -q tests/contract

test-security:
	cd apps/api && $(API_PY) pytest -q tests/security

test-e2e:
	cd apps/web && npm run test:e2e

audit-verify:
	cd apps/api && $(API_PY) gov.api.application.audit.verify

check: lint test test-contract test-security
