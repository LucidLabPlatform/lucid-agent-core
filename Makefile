PYTHON ?= python3
VENV ?= .venv

.PHONY: help setup setup-venv dev test test-unit test-integration test-coverage test-deps build clean dist

help:
	@echo "LUCID Agent Core v1.0.0"
	@echo "  make setup           - Create .env from env.example"
	@echo "  make setup-venv      - Create .venv, install project + deps"
	@echo "  make dev             - Run agent locally"
	@echo "  make test            - Unit + integration tests"
	@echo "  make test-unit       - Unit tests only"
	@echo "  make test-integration - Integration tests (if any)"
	@echo "  make test-coverage   - Tests with coverage report"
	@echo "  make build           - Build wheel and sdist (run make setup-venv first)"
	@echo "  make clean           - Remove build artifacts"

setup:
	@if [ -f .env ]; then \
		echo ".env exists."; \
	else \
		cp src/lucid_agent_core/env.example .env; \
		echo "Created .env from env.example. Edit MQTT_HOST, MQTT_PORT, AGENT_USERNAME, AGENT_PASSWORD."; \
	fi

setup-venv:
	@test -d $(VENV) || ($(PYTHON) -m venv $(VENV) && echo "Created $(VENV).")
	@$(VENV)/bin/pip install -q -e ".[dev]"
	@$(VENV)/bin/pip install -q build
	@echo "Ready. Run 'make dev' or 'make build'."

dev:
	@test -f .env || (echo "Run 'make setup' first." && exit 1)
	@test -d $(VENV) || (echo "Run 'make setup-venv' first." && exit 1)
	@set -a && . ./.env && set +a && $(VENV)/bin/python -m lucid_agent_core.main run

test: test-unit test-integration
	@echo "All tests passed."

test-unit:
	@pytest tests/unit/ -v -q

test-integration:
	@if [ -d tests/integration ]; then \
		(test -f .env && set -a && . ./.env && set +a); \
		pytest tests/integration/ -v -q; \
	else \
		echo "No integration tests."; \
	fi

test-coverage:
	@pytest tests/unit/ --cov=src/lucid_agent_core --cov-report=html --cov-report=term-missing -q

test-deps:
	@pip install -r requirements.txt

build:
	@test -d $(VENV) || (echo "Run 'make setup-venv' first." && exit 1)
	@$(VENV)/bin/python -m build

clean:
	@rm -rf build/ dist/ *.egg-info src/*.egg-info
