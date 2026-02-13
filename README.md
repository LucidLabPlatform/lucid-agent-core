# LUCID Agent Core

`lucid-agent-core` is the MQTT runtime agent for LUCID. It connects to a broker, publishes retained online/offline status with LWT, subscribes to component install commands, and loads components from the registry.

## Quick Start

### Prerequisites
- Python 3.11+
- MQTT broker
- MQTT credentials (`AGENT_USERNAME` / `AGENT_PASSWORD`)

### Setup

```bash
make setup        # Create .env from env.example
make setup-venv   # Create .venv and install project
```

Edit `.env` and set `MQTT_HOST`, `MQTT_PORT`, `AGENT_USERNAME`, `AGENT_PASSWORD`.

### Run locally

```bash
make dev
```

## MQTT Contract (v1.0.0)

### Publishes
- `lucid/agents/<agent_username>/status` (retained, QoS 1)

Status payload:
```json
{
  "state": "online",
  "ts": "2026-02-09T16:30:50.123456+00:00",
  "version": "1.0.0"
}
```

### Subscribes
- `lucid/agents/<agent_username>/core/cmd/components/install` (QoS 1)

Install command payload (JSON):
```json
{
  "request_id": "req-1",
  "component_id": "cpu",
  "version": "1.0.0",
  "entrypoint": "lucid_agent_cpu.component:CpuComponent",
  "source": {
    "type": "github_release",
    "owner": "LucidLabPlatform",
    "repo": "lucid-agent-cpu",
    "tag": "v1.0.0",
    "asset": "lucid_agent_cpu-1.0.0-py3-none-any.whl",
    "sha256": "<64-hex-chars>"
  }
}
```

## Build and Test

```bash
make test-unit      # Unit tests
make test-coverage  # With coverage report
make setup-venv     # One-time
make build          # Build wheel and sdist
```

## Operator Guide

See [docs/RELEASE_USAGE.md](docs/RELEASE_USAGE.md) for service install, troubleshooting, and day-2 operations.