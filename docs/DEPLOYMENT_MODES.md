# Agent-Core Deployment — Local Run

Agent runs as a Python process directly on the host. No Docker required for the agent process itself.

---

## Setup

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create `.env` from `env.example`:
   ```bash
   cp env.example .env
   ```

3. Configure `.env`:
   - Set `LUCID_MODE=local`
   - Set MQTT broker settings: `MQTT_HOST`, `MQTT_PORT`, `AGENT_USERNAME`, `AGENT_PASSWORD`
   - Set `AGENT_VERSION`

---

## Run

```bash
make dev
```

---

## Environment Variables

**Required:**
- `LUCID_MODE=local`
- `MQTT_HOST` — MQTT broker hostname/IP
- `MQTT_PORT` — MQTT broker port (typically 1883)
- `AGENT_USERNAME` — MQTT username for the agent
- `AGENT_PASSWORD` — MQTT password for the agent
- `AGENT_VERSION` — Agent version (should match `VERSION` file)

**Optional:**
- `AGENT_HEARTBEAT` — Heartbeat interval in seconds (default: 30)

---

## Troubleshooting

**Agent does not start:**
- Check `.env` file exists and has required variables
- Verify `LUCID_MODE=local`
- Check MQTT broker is accessible (`MQTT_HOST`, `MQTT_PORT`)
- Verify credentials (`AGENT_USERNAME`, `AGENT_PASSWORD`)

---

## See Also

- **README.md** — Quick start and overview
- **env.example** — Configuration template
