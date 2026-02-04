PYTHON ?= python3
VENV ?= .venv

.PHONY: help setup setup-venv dev test test-unit test-integration test-coverage test-deps install-component build clean dist

help:
	@echo "LUCID Agent Core"
	@echo "  make setup        - Create .env from env.example"
	@echo "  make setup-venv   - Create .venv and install build (for packaging)"
	@echo "  make dev          - Run agent locally: $(PYTHON) -m lucid_agent_core.main"
	@echo "  make install-component - Install+start a fake component (use: make install-component TYPE=sensor ID=my_sensor_1 [CONFIG='{...}'])"
	@echo "  make test         - Unit + integration tests"
	@echo "  make test-unit    - Unit tests only"
	@echo "  make test-integration - Integration tests"
	@echo "  make test-coverage - Tests with coverage"
	@echo "  make build        - Build wheel and sdist (uses $(VENV), run make setup-venv first)"
	@echo "  make clean        - Remove build artifacts"

setup:
	@if [ -f .env ]; then \
		echo ".env exists."; \
	else \
		cp env.example .env; \
		echo "Created .env from env.example. Edit LUCID_MODE, MQTT, and registry."; \
	fi

setup-venv:
	@test -d $(VENV) || ($(PYTHON) -m venv $(VENV) && echo "Created $(VENV).")
	@$(VENV)/bin/pip install -q build
	@echo "Ready. Run 'make build' to build the package."

dev:
	@test -f .env || (echo "Run 'make setup' first." && exit 1)
	@set -a && . ./.env && set +a && $(PYTHON) -m lucid_agent_core.main

install-component:
	@test -f .env || (echo "Run 'make setup' first and set MQTT_*, AGENT_*." && exit 1)
	@test -n "$${TYPE}" || (echo "Usage: make install-component TYPE=sensor ID=my_sensor_1 [CONFIG='{\"key\":\"val\"}']" && exit 1)
	@test -n "$${ID}" || (echo "Usage: make install-component TYPE=sensor ID=my_sensor_1 [CONFIG='{\"key\":\"val\"}']" && exit 1)
	@set -a && . ./.env && set +a && \
		[ -n '$(CONFIG)' ] && export CONFIG='$(CONFIG)'; \
		$(PYTHON) scripts/install_component.py --type $${TYPE} --id $${ID}

test: test-unit test-integration
	@echo "All tests passed."

test-unit:
	@pytest -m unit -v

test-integration:
	@if [ -f .env ]; then set -a && . ./.env && set +a; fi; pytest -m integration -v

test-coverage:
	@pytest --cov=src --cov-report=html --cov-report=term-missing

test-deps:
	@pip install -r requirements.txt

build:
	@test -d $(VENV) || (echo "Run 'make setup-venv' first." && exit 1)
	@$(VENV)/bin/python -m build

clean:
	@rm -rf build/ dist/ *.egg-info src/*.egg-info
