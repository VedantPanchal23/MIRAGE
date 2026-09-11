.PHONY: setup dev test test-unit test-integration lint format migrate docker-up docker-down clean

PYTHON ?= python

setup:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

dev:
	docker compose up -d
	uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload

docker-up:
	docker compose up -d

docker-down:
	docker compose down

migrate:
	alembic upgrade head

test:
	pytest

test-unit:
	pytest -m unit

test-integration:
	pytest -m integration

lint:
	ruff check .
	mypy --strict shared/ db/

format:
	ruff format .

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build *.egg-info
