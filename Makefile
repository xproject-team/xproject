.PHONY: up down build test lint migrate seed logs shell-api shell-db

# ── Docker lifecycle ───────────────────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

# ── Database ───────────────────────────────────────────────────────────────────

migrate:
	docker compose exec api alembic upgrade head

migrate-create:
	@read -p "Migration message: " msg; \
	docker compose exec api alembic revision --autogenerate -m "$$msg"

seed:
	docker compose exec api python -m app.scripts.seed

# ── Testing ────────────────────────────────────────────────────────────────────

test:
	docker compose exec api pytest tests/ -v

test-cov:
	docker compose exec api pytest tests/ -v --cov=app --cov-report=term-missing

# ── Linting ────────────────────────────────────────────────────────────────────

lint:
	docker compose exec api ruff check app/ tests/
	docker compose exec api ruff format --check app/ tests/

lint-fix:
	docker compose exec api ruff check --fix app/ tests/
	docker compose exec api ruff format app/ tests/

# ── Shells ─────────────────────────────────────────────────────────────────────

shell-api:
	docker compose exec api bash

shell-db:
	docker compose exec db psql -U xproject xproject
