.PHONY: setup dev test test-unit test-integration lint format migrate docker-up docker-down clean

ifeq ($(OS),Windows_NT)
    VENV_BIN := .venv/Scripts
else
    VENV_BIN := .venv/bin
endif

PYTHON ?= $(VENV_BIN)/python
PYTEST ?= $(VENV_BIN)/pytest
RUFF   ?= $(VENV_BIN)/ruff
MYPY   ?= $(VENV_BIN)/mypy
UVICORN ?= $(VENV_BIN)/uvicorn
ALEMBIC ?= $(VENV_BIN)/alembic

setup:
	py -3.12 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

dev:
	docker compose up -d
	$(UVICORN) gateway.main:app --host 0.0.0.0 --port 8000 --reload

docker-up:
	docker compose up -d

docker-down:
	docker compose down

migrate:
	$(ALEMBIC) upgrade head

test:
	$(PYTEST)

test-unit:
	$(PYTEST) -m unit

test-integration:
	$(PYTEST) -m integration

lint:
	$(RUFF) check .
	$(MYPY) --strict workers/ models/ gateway/ shared/ db/

format:
	$(RUFF) format .

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build *.egg-info
