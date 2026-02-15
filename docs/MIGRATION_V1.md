# Migration Guide: Pre-v1.0.0 to v1.0.0

## Overview

Version 1.0.0 introduces a **strict uninstall requirement**: all installed components must have a `dist_name` field in the registry. This field stores the Python distribution name used by `pip uninstall`.

Pre-v1.0.0 registries do not have this field, which prevents uninstall from working.

## Migration Strategy

### Option 1: Provide dist_name Explicitly (Recommended)

For components installed before v1.0.0, you can provide the `dist_name` in the uninstall command payload:

```bash
mosquitto_pub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/cmd/components/uninstall" \
  -m '{
    "request_id": "migrate-uninstall-1",
    "component_id": "cpu",
    "dist_name": "lucid-agent-cpu"
  }'
```

**How to determine dist_name:**

1. From wheel filename: `lucid_agent_cpu-1.0.0-py3-none-any.whl` → `lucid-agent-cpu`
2. From registry `wheel_url` field (if present)
3. From `pip list` output on the agent
4. Apply PEP 503 normalization:
   - Lowercase
   - Replace runs of `[-_.]` with single hyphen
   - Example: `Lucid_Agent.CPU` → `lucid-agent-cpu`

### Option 2: Fresh Install

If you cannot determine the dist_name:

1. Manually pip uninstall the component on the agent
2. Manually remove from registry: `sudo rm /var/lib/lucid/components.json`
3. Reinstall via MQTT install command (will include dist_name)

### Option 3: Manual Registry Edit

If you have shell access and know the dist_name:

```bash
# Edit registry to add dist_name
sudo vi /var/lib/lucid/components.json

# Add "dist_name" field to each component:
{
  "cpu": {
    "repo": "LucidLabPlatform/lucid-agent-cpu",
    "version": "1.0.0",
    "dist_name": "lucid-agent-cpu",  # <-- ADD THIS
    ...
  }
}

# Restart agent to reload registry
sudo systemctl restart lucid-agent-core
```

## Verifying Migration

After migration, uninstall should work without providing dist_name:

```bash
mosquitto_pub -h $MQTT_HOST -p $MQTT_PORT \
  -u $MQTT_USERNAME -P $MQTT_PASSWORD \
  -t "${BASE_TOPIC}/core/cmd/components/uninstall" \
  -m '{
    "request_id": "test-uninstall",
    "component_id": "cpu"
  }'
```

Expected result: `ok=true, restart_required=true`

## Error Messages

**Missing dist_name (no migration path used):**
```json
{
  "request_id": "...",
  "ok": false,
  "error": "registry missing dist_name for component; provide dist_name in uninstall payload for migration"
}
```

**Solution:** Use Option 1 above and provide `dist_name` in the uninstall payload.

## Future Installs

All installs via v1.0.0+ automatically include `dist_name` in the registry. No migration needed for newly installed components.

## PEP 503 Normalization Reference

Distribution names are normalized per [PEP 503](https://www.python.org/dev/peps/pep-0503/):

- Convert to lowercase
- Replace any run of `[-_.]` with a single hyphen

Examples:
- `lucid_agent_cpu` → `lucid-agent-cpu`
- `Lucid.Agent.CPU` → `lucid-agent-cpu`
- `LUCID--Agent__CPU` → `lucid-agent-cpu`

This ensures pip can find the correct package regardless of how it was originally named.
