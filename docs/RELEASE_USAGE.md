# LUCID Agent Core — Release & Operator Guide

## System service install (Linux, systemd)

Install as a systemd service (requires root):

```bash
sudo lucid-agent-core install-service
```

This will:
- Create system user `lucid`
- Create `/home/lucid/lucid-agent-core/agent-core.env` from packaged template (never overwrites existing)
- Create `/home/lucid/lucid-agent-core/venv` and install the agent
- Install systemd unit `/etc/systemd/system/lucid-agent-core.service`
- Enable the service

Before first run, edit `/home/lucid/lucid-agent-core/agent-core.env` and set:
- `MQTT_HOST`
- `MQTT_PORT`
- `AGENT_USERNAME`
- `AGENT_PASSWORD`
- `AGENT_HEARTBEAT` (optional, 0 = disabled)

Start the service:
```bash
sudo systemctl start lucid-agent-core
sudo systemctl status lucid-agent-core
```

## Component registry

Installed components are recorded in `/home/lucid/lucid-agent-core/data/components_registry.json`. The agent loads components from this registry at startup. Component installs (via MQTT) update this file.

## Troubleshooting

- **MQTT connection failed**: Check broker reachability, credentials in env, and network/firewall.
- **Component load errors**: Inspect registry at `/home/lucid/lucid-agent-core/data/components_registry.json` and logs.
- **Logs**: `journalctl -u lucid-agent-core -f` (when running as service).
