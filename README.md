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

## Testing Offline Status

The agent publishes `state: offline` in two scenarios:

### 1. Graceful Shutdown (Manual Publish)
```bash
# Start the agent
python main.py

# In another terminal, monitor status
mosquitto_sub -t "lucid/agents/+/status" -v

# Stop with Ctrl+C - agent manually publishes offline before disconnecting
```

### 2. Unexpected Disconnect (LWT Trigger)
```bash
# Start the agent
python main.py

# Kill it forcefully (LWT will be published by broker)
kill -9 <pid>

# Or simulate network failure, power loss, etc.
```

**Note:** LWT (Last Will and Testament) only triggers on unexpected disconnects. For graceful shutdowns, the agent manually publishes the offline status before disconnecting.

## File Structure

```
lucid-agent-core/
├── config.py          # Device ID + broker credentials
├── mqtt_client.py     # MQTT connection, LWT, status publishing
├── main.py           # Entry point: start, sleep, die
└── requirements.txt  # Dependencies (paho-mqtt only)
```