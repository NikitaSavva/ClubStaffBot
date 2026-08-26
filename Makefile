.PHONY: build up down migrate lint typecheck


build:
    docker compose build

up:
	docker compose up -d --wait

down:
	docker compose down

migrate:
    docker compose run --rm api alembic upgrade head

lint:
	ruff check .

typecheck:
	mypy
