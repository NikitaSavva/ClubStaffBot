.PHONY: docker-up docker-down docker-status test lint typecheck

docker-up:
	docker compose up -d --wait

docker-down:
	docker compose down

docker-status:
	docker compose ps

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy
