# LUCID Agent Core v0 - Step 1.2

**Minimal agent skeleton to prove MQTT broker + ACLs work correctly.**

## What This Does

This agent does exactly three things:

1. ✅ Connects to MQTT using its own identity
2. ✅ Publishes a retained `status = online`
3. ✅ Goes offline via LWT when killed

**No install logic. No plugins. No hot-reload. No cleverness.**

## Agent Behavior

| Requirement | Implementation |
|------------|----------------|
| **Client ID** | `lucid.agent.<username>` |
| **Username** | `<username>` (configurable) |
| **On Connect** | Publishes (retained) to `lucid/agents/<username>/status`<br>`{"state": "online", "ts": "...", "agent_version": "0.0.0"}` |
| **LWT** | Publishes (retained) to `lucid/agents/<username>/status`<br>`{"state": "offline", "ts": "..."}` |

## Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

## Configuration

**All environment variables are required.** Set them before running:

```bash
export HOST="localhost"
export PORT="1883"
export USERNAME="mqtt-user"
export PASSWORD="your-password"
export VERSION="0.0.0"
```


## Usage

```bash
# Start the agent
python main.py

# The agent will:
# - Connect to broker
# - Publish online status (retained)
# - Stay running until killed
# - LWT will publish offline status when terminated
```

## Testing the LWT

1. Start the agent: `python main.py`
2. Monitor the status topic: `mosquitto_sub -t "lucid/agents/+/status" -v`
3. Kill the agent: `Ctrl+C` or `kill <pid>`
4. Verify the broker publishes the LWT with `state: offline`

## File Structure

```
lucid-agent-core/
├── config.py          # Device ID + broker credentials
├── mqtt_client.py     # MQTT connection, LWT, status publishing
├── main.py           # Entry point: start, sleep, die
└── requirements.txt  # Dependencies (paho-mqtt only)
```