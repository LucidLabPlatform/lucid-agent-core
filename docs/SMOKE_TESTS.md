# Core MQTT Contract v1.0.0 — Smoke Tests

This document provides smoke test procedures for verifying the complete core MQTT contract implementation using `mosquitto_pub` and `mosquitto_sub`.

## Prerequisites

- MQTT broker running (e.g., Mosquitto)
- `mosquitto_pub` and `mosquitto_sub` installed
- Agent running with valid credentials
- Agent username: `test_agent` (adjust topics accordingly)

## Environment Setup

```bash
export MQTT_HOST="localhost"
export MQTT_PORT="1883"
export MQTT_USERNAME="test_agent"
export MQTT_PASSWORD="your_password"
export BASE_TOPIC="lucid/agents/test_agent"
```

## Test 1: Boot Test — Retained Snapshots on Connect

**Goal:** Verify all retained snapshots are published when agent connects.

### Steps

1. Subscribe to all retained topics:

```bash
mosquitto_sub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/#" -v
```

2. Start the agent (or restart it)

3. Verify the following retained messages are published:

```
lucid/agents/test_agent/status
lucid/agents/test_agent/core/metadata
lucid/agents/test_agent/core/state
lucid/agents/test_agent/core/components
lucid/agents/test_agent/core/cfg/state
```

### Expected Payloads

**status:**
```json
{
  "state": "online",
  "version": "1.0.0",
  "agent_id": "test_agent",
  "ts": "2026-02-14T12:00:00.000000+00:00"
}
```

**core/metadata:**
```json
{
  "agent_id": "test_agent",
  "version": "1.0.0",
  "ts": "2026-02-14T12:00:00.000000+00:00"
}
```

**core/state:**
```json
{
  "agent_id": "test_agent",
  "state": "running",
  "ts": "2026-02-14T12:00:00.000000+00:00"
}
```

**core/components:**
```json
{
  "count": 0,
  "components": {},
  "ts": "2026-02-14T12:00:00.000000+00:00"
}
```

**core/cfg/state:**
```json
{
  "cfg": {},
  "ts": "2026-02-14T12:00:00.000000+00:00"
}
```

## Test 2: Component Install

**Goal:** Verify install command publishes result event and updates retained snapshot.

### Steps

1. Subscribe to install events:

```bash
mosquitto_sub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/evt/components/install_result" \
  -t "${BASE_TOPIC}/core/components" -v
```

2. Publish install command:

```bash
mosquitto_pub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/cmd/components/install" \
  -m '{
    "request_id": "test-install-1",
    "component_id": "cpu",
    "version": "1.0.0",
    "entrypoint": "lucid_agent_cpu.component:CpuComponent",
    "source": {
      "type": "github_release",
      "owner": "LucidLabPlatform",
      "repo": "lucid-agent-cpu",
      "tag": "v1.0.0",
      "asset": "lucid_agent_cpu-1.0.0-py3-none-any.whl",
      "sha256": "YOUR_SHA256_HERE"
    }
  }'
```

### Expected Results

1. **install_result event** (non-retained):

```json
{
  "request_id": "test-install-1",
  "ok": true,
  "component_id": "cpu",
  "version": "1.0.0",
  "restart_required": true,
  "sha256": "...",
  "ts": "..."
}
```

2. **core/components snapshot** (retained, updated):

```json
{
  "count": 1,
  "components": {
    "cpu": {
      "repo": "LucidLabPlatform/lucid-agent-cpu",
      "version": "1.0.0",
      "wheel_url": "...",
      "entrypoint": "lucid_agent_cpu.component:CpuComponent",
      "sha256": "...",
      "dist_name": "lucid-agent-cpu",
      "source": {...},
      "installed_at": "..."
    }
  },
  "ts": "..."
}
```

3. **Agent should restart** (if systemd is configured)

## Test 3: Component Uninstall

**Goal:** Verify uninstall command publishes result event and updates retained snapshot.

### Prerequisites

If testing with components installed before v1.0.0 that lack `dist_name` in registry, see `docs/MIGRATION_V1.md` for migration options.

### Steps

1. Subscribe to uninstall events:

```bash
mosquitto_sub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/evt/components/uninstall_result" \
  -t "${BASE_TOPIC}/core/components" -v
```

2. Publish uninstall command:

```bash
mosquitto_pub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/cmd/components/uninstall" \
  -m '{
    "request_id": "test-uninstall-1",
    "component_id": "cpu"
  }'
```

**For pre-v1.0.0 components (migration):**

```bash
mosquitto_pub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/cmd/components/uninstall" \
  -m '{
    "request_id": "test-uninstall-1",
    "component_id": "cpu",
    "dist_name": "lucid-agent-cpu"
  }'
```

### Expected Results

1. **uninstall_result event** (non-retained):

```json
{
  "request_id": "test-uninstall-1",
  "ok": true,
  "component_id": "cpu",
  "noop": false,
  "restart_required": true,
  "ts": "..."
}
```

2. **core/components snapshot** (retained, updated):

```json
{
  "count": 0,
  "components": {},
  "ts": "..."
}
```

3. **Agent should restart** (if systemd is configured)

### Test 3b: Idempotent Uninstall

Uninstall the same component again:

```bash
mosquitto_pub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/cmd/components/uninstall" \
  -m '{
    "request_id": "test-uninstall-2",
    "component_id": "cpu"
  }'
```

**Expected:** `ok=true, noop=true, restart_required=false`

## Test 4: Config Set

**Goal:** Verify config set updates retained cfg/state and publishes result event.

### Steps

1. Subscribe to config events:

```bash
mosquitto_sub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/evt/cfg_set_result" \
  -t "${BASE_TOPIC}/core/cfg/state" -v
```

2. Publish config set command:

```bash
mosquitto_pub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/cfg/set" \
  -m '{
    "request_id": "test-cfg-1",
    "set": {
      "heartbeat_s": 30,
      "telemetry_enabled": true
    }
  }'
```

### Expected Results

1. **cfg_set_result event** (non-retained):

```json
{
  "request_id": "test-cfg-1",
  "ok": true,
  "applied": {
    "heartbeat_s": 30,
    "telemetry_enabled": true
  },
  "ts": "..."
}
```

2. **core/cfg/state snapshot** (retained, updated):

```json
{
  "cfg": {
    "heartbeat_s": 30,
    "telemetry_enabled": true
  },
  "ts": "..."
}
```

3. **Heartbeat interval changed:** Agent should now publish status every 30 seconds

### Test 4b: Invalid Config

Test validation by sending invalid config:

```bash
mosquitto_pub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/cfg/set" \
  -m '{
    "request_id": "test-cfg-invalid",
    "set": {
      "unknown_key": "value"
    }
  }'
```

**Expected:** `ok=false, error="unknown config key: unknown_key"`

**Verify:** Retained `core/cfg/state` should NOT be updated

## Test 5: Refresh

**Goal:** Verify refresh republishes all retained snapshots.

### Steps

1. Subscribe to all retained snapshots and refresh event:

```bash
mosquitto_sub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/#" -v
```

2. Publish refresh command:

```bash
mosquitto_pub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/cmd/refresh" \
  -m '{
    "request_id": "test-refresh-1"
  }'
```

### Expected Results

1. **refresh_result event** (non-retained):

```json
{
  "request_id": "test-refresh-1",
  "ok": true,
  "snapshots_updated": ["metadata", "state", "components", "cfg"],
  "ts": "..."
}
```

2. **All retained snapshots republished:**
   - `core/metadata`
   - `core/state`
   - `core/components`
   - `core/cfg/state`

(Timestamps should be updated to current time)

## Test 6: Heartbeat

**Goal:** Verify periodic status publishing.

### Steps

1. Set heartbeat to 10 seconds (if not already set via Test 4):

```bash
mosquitto_pub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/cfg/set" \
  -m '{
    "request_id": "test-hb-1",
    "set": {
      "heartbeat_s": 10
    }
  }'
```

2. Subscribe to status topic:

```bash
mosquitto_sub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/status" -v
```

3. Wait 10+ seconds

**Expected:** Status payload is republished every 10 seconds with updated timestamp

## Test 7: LWT (Last Will and Testament)

**Goal:** Verify offline status is published when agent disconnects unexpectedly.

### Steps

1. Subscribe to status:

```bash
mosquitto_sub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/status" -v
```

2. Kill the agent process (simulate crash):

```bash
sudo pkill -9 -f lucid-agent-core
```

**Expected:** Broker publishes LWT message:

```json
{
  "state": "offline",
  "version": "1.0.0",
  "agent_id": "test_agent",
  "ts": "..."
}
```

(Note: This is a retained message)

## Verification Checklist

- [ ] Boot test: All 5 retained snapshots published on connect
- [ ] Install: Result event published, snapshot updated, restart triggered
- [ ] Uninstall: Result event published, snapshot updated, restart triggered
- [ ] Uninstall idempotency: noop=true for non-existent component
- [ ] Config set: Valid config updates retained state and heartbeat
- [ ] Config set: Invalid config returns error, no state change
- [ ] Refresh: All snapshots republished with updated timestamps
- [ ] Heartbeat: Status republished at configured interval
- [ ] LWT: Offline status published on unexpected disconnect

## Notes

- All event topics are **non-retained**
- All state snapshots are **retained**
- All messages use **QoS 1**
- All payloads include `schema: "lucid.core.v1.0.0"`
- Timestamps are in ISO8601 UTC format
- Agent restarts are handled via systemd (if configured)
