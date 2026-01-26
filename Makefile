.PHONY: help setup run stop logs restart dev test test-unit test-integration test-coverage test-deps build-runtime install-component

help:
	@echo "LUCID Agent Core"
	@echo "  make setup        - Create .env from env.example (or migrate docker/.env)"
	@echo "  make run          - Start agent in Docker (LUCID_MODE=docker)"
	@echo "  make stop         - Stop agent (docker compose down)"
	@echo "  make logs         - Agent logs"
	@echo "  make restart      - Restart agent"
	@echo "  make dev          - Run agent locally (LUCID_MODE=local): python src/main.py"
	@echo "  make build-runtime     - Build runtime image (lucid-agent-core:*-runtime) for components"
	@echo "  make install-component - Install+start a fake component (use: make install-component TYPE=sensor ID=my_sensor_1 [CONFIG='{...}'])"
	@echo "  make test         - Unit + integration tests"
	@echo "  make test-unit    - Unit tests only"
	@echo "  make test-integration - Integration tests"
	@echo "  make test-coverage - Tests with coverage"

setup:
	@if [ -f .env ]; then \
		echo ".env exists."; \
	elif [ -f docker/.env ]; then \
		cp docker/.env .env; \
		echo "Created .env from docker/.env. Edit LUCID_MODE and other settings."; \
	else \
		cp env.example .env; \
		echo "Created .env from env.example. Edit LUCID_MODE, MQTT, and registry."; \
	fi

run:
	@test -f .env || (echo "Run 'make setup' first." && exit 1)
	@set -a && . ./.env && set +a && \
		if [ "$${LUCID_MODE}" = "local" ]; then \
			echo "LUCID_MODE=local; use 'make dev' for local run."; exit 1; \
		fi && \
		docker compose -f docker/docker-compose.yml --env-file .env up -d

stop:
	@docker compose -f docker/docker-compose.yml down

logs:
	@docker compose -f docker/docker-compose.yml logs -f

restart:
	@docker compose -f docker/docker-compose.yml restart

dev:
	@test -f .env || (echo "Run 'make setup' first." && exit 1)
	@set -a && . ./.env && set +a && \
		if [ "$${LUCID_MODE}" = "docker" ]; then \
			echo "LUCID_MODE=docker; use 'make run' for Docker."; exit 1; \
		fi && \
		python src/main.py

build-runtime:
	@VERSION=$$(cat VERSION 2>/dev/null || echo "latest"); \
	echo "Building lucid-agent-core:$${VERSION}-runtime"; \
	docker build -f docker/Dockerfile --target runtime -t lucid-agent-core:$${VERSION}-runtime . && \
	if [ "$${VERSION}" != "latest" ]; then \
		docker tag lucid-agent-core:$${VERSION}-runtime lucid-agent-core:latest-runtime; \
		echo "Also tagged lucid-agent-core:latest-runtime"; \
	fi

install-component:
	@test -f .env || (echo "Run 'make setup' first and set MQTT_*, AGENT_*." && exit 1)
	@test -n "$${TYPE}" || (echo "Usage: make install-component TYPE=sensor ID=my_sensor_1 [CONFIG='{\"key\":\"val\"}']" && exit 1)
	@test -n "$${ID}" || (echo "Usage: make install-component TYPE=sensor ID=my_sensor_1 [CONFIG='{\"key\":\"val\"}']" && exit 1)
	@set -a && . ./.env && set +a && \
		[ -n '$(CONFIG)' ] && export CONFIG='$(CONFIG)'; \
		python scripts/install_component.py --type $${TYPE} --id $${ID}

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
