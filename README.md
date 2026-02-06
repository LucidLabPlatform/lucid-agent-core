# LUCID Agent Core

Agent that connects to an MQTT broker and manages hardware components.

---

## Quick Start

1. **Prerequisites:** MQTT broker running (e.g. from lucid-infra)

2. **Configure:** Set env once per machine so the installed package works from any directory:
   - **Option A:** `mkdir -p ~/.config/lucid-agent-core && cp env.example ~/.config/lucid-agent-core/.env` — then edit that file. The app loads it automatically.
   - **Option B:** In the project dir, `make setup` or `cp env.example .env` — for local dev; a `.env` in the current directory overrides the global config.
   - Set `MQTT_HOST`, `MQTT_PORT`, `AGENT_USERNAME`, `AGENT_PASSWORD`.
   - Version is read from the installed `lucid-agent-core` package metadata.

3. **Run from source (dev):** `make dev` (requires `LUCID_MODE=local` in your `.env`).

4. **Build & install package (CLI `lucid-agent-core`):**
   - **Build artifacts:**  
     ```bash
     make setup-venv   # one-time: create .venv and install build tool
     make build        # builds wheel + sdist into dist/
     ```
   - **Install into the project venv:**  
     ```bash
     .venv/bin/pip install dist/lucid_agent_core-*.whl
     ```
   - **Run the installed CLI:**  
     - Without activating venv:  
       ```bash
       /Users/farahorfaly/Desktop/LUCID/lucid-agent-core/.venv/bin/lucid-agent-core
       ```
     - Or activate venv first:  
       ```bash
       cd /Users/farahorfaly/Desktop/LUCID/lucid-agent-core
       source .venv/bin/activate
       lucid-agent-core
       ```

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
