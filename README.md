# LUCID Agent Core

MQTT runtime agent for LUCID: connects to a broker, publishes retained metadata/status/state/cfg, streams logs and telemetry when enabled, and loads components from the registry. Single entrypoint: `lucid-agent-core run` (interactive) or systemd service.

---

## Versioning

Version is derived from Git tags via [setuptools_scm](https://github.com/pypa/setuptools_scm). Tag releases as `v1.2.3`; the package version becomes `1.2.3`.

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

Edit `.env` and set `MQTT_HOST`, `MQTT_PORT`, `AGENT_USERNAME`, `AGENT_PASSWORD`. Optionally set `AGENT_HEARTBEAT` (seconds; 0 = disabled) and `LUCID_LOG_LEVEL` (DEBUG, INFO, WARNING, ERROR).

### Run locally

```bash
make dev
```

## MQTT Contract (v1.0.0)

Unified topics under `lucid/agents/<agent_username>/`. No `core/` nesting.

### Agent publishes (retained)
- `metadata`, `status`, `state`, `cfg` (cfg includes `telemetry`, `heartbeat_s`, `log_level`, `logs_enabled`)

### Agent streams (when enabled)
- `logs` (batched; gated by `cfg.logs_enabled`)
- `telemetry/<metric>` (e.g. `cpu_percent`, `memory_percent`, `disk_percent`; gated by `cfg.telemetry.metrics.<metric>.enabled`)

### Agent subscribes (commands)
- `cmd/ping`, `cmd/restart`, `cmd/refresh`, `cmd/cfg/set`
- `cmd/components/install`, `cmd/components/uninstall`, `cmd/components/enable`, `cmd/components/disable`, `cmd/components/upgrade`
- `cmd/core/upgrade`
- Per-component: `components/<component_id>/cmd/reset`, `cmd/ping`, `cmd/cfg/set`

See [MQTT_CONTRACT_V1.md](../MQTT_CONTRACT_V1.md) in the repo root for full topic list and payload contracts.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MQTT_HOST` | Yes | MQTT broker hostname. |
| `MQTT_PORT` | Yes | MQTT broker port (1–65535). |
| `AGENT_USERNAME` | Yes | Agent identity (topic prefix). |
| `AGENT_PASSWORD` | Yes | MQTT password. |
| `AGENT_HEARTBEAT` | No | Seconds between retained status refresh; default `0` (disabled). |
| `LUCID_LOG_LEVEL` | No | Startup log level (DEBUG, INFO, WARNING, ERROR). Overridable via MQTT `cmd/cfg/set`. |
| `LUCID_AGENT_CORE_WHEEL` | No | Path to local wheel for install/upgrade (skips download). |
| `LUCID_AGENT_BASE_DIR` | No | Override base dir for agent files (default `/home/lucid/lucid-agent-core`). For testing. |

## System service install (Linux, systemd)

```bash
sudo lucid-agent-core install-service
```

Creates user `lucid`, `/home/lucid/lucid-agent-core/` (venv, agent-core.env, data, logs, run), and systemd unit. Edit `agent-core.env` with `MQTT_HOST`, `MQTT_PORT`, `AGENT_USERNAME`, `AGENT_PASSWORD` before first run. Optional: `--wheel PATH` or `LUCID_AGENT_CORE_WHEEL` for local wheel install.

```bash
sudo systemctl start lucid-agent-core
sudo systemctl status lucid-agent-core
```

Component registry: `/home/lucid/lucid-agent-core/data/components_registry.json`. Logs: `journalctl -u lucid-agent-core -f`.

### Running with hardware (e.g. LED strip)

Use the **LED strip helper daemon** so agent-core stays as user `lucid`: install lucid-component-led-strip with the `[pi]` extra, then install and start `lucid-led-strip-helper.service`. See the lucid-component-led-strip docs.

## Troubleshooting

- **MQTT connection failed**: Check broker, credentials in env, network/firewall.
- **Component load errors**: Inspect registry and logs.

## Documentation

Full topic and payload details: [MQTT_CONTRACT_V1.md](../MQTT_CONTRACT_V1.md). Smoke tests, migration, verification: [docs/](../docs/) in the repo root.

## Build and Test

```bash
make test-unit      # Unit tests
make test-coverage  # With coverage report
make setup-venv     # One-time
make build          # Build wheel and sdist
```