# LUCID Agent Core

Agent that connects to an MQTT broker and manages component Docker containers.

---

## Quick Start

1. **Prerequisites:** MQTT broker running (e.g. from lucid-infra)

2. **Configure:** `make setup` (creates `.env` from `env.example`) or `cp env.example .env`
   - Set `MQTT_HOST`, `MQTT_PORT`, `AGENT_USERNAME`, `AGENT_PASSWORD`
   - Set `AGENT_VERSION`
   - Ensure `LUCID_MODE=local`

3. **Run:** `make dev` (requires `LUCID_MODE=local`)

---

## Deployment

**Local run:** `make dev` (Python process on host)

Set `LUCID_MODE=local` in `.env`. See `env.example` for configuration.

---

## MQTT Topics

**Publishes:**
- `lucid/agents/{username}/status` — Agent status (online/offline)

---

## Tests

- Unit: `make test-unit` or `pytest -m unit -v`
- Integration: `make test-integration` or `pytest -m "integration and not e2e" -v` (requires broker)

---

## Troubleshooting

- **Agent does not start** — Check `.env` exists, `LUCID_MODE=local`, MQTT broker accessible
