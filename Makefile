.PHONY: dev-up dev-down migrate seed api-dev web-dev test lint

dev-up:
	docker compose up -d postgres

dev-down:
	docker compose down

migrate:
	cd api && alembic upgrade head

seed:
	cd api && python -m scripts.seed

api-dev:
	cd api && uvicorn app.main:app --reload

web-dev:
	cd web && npm run dev

test:
	cd api && TEST_DATABASE_URL=$${TEST_DATABASE_URL:-postgresql+asyncpg://redactproof:redactproof@localhost:5432/redactproof_test} pytest

lint:
	cd api && ruff check . && mypy app
	cd web && npm run lint
