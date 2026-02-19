"""
Retained snapshot builders for LUCID Agent Core — unified v1.0.0 contract.

Pure functions that build MQTT retained payload dicts.
No schema versioning; no legacy fields.
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore


def now_iso8601() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()


def build_metadata(agent_id: str, version: str) -> dict[str, Any]:
    """
    Build retained metadata. Contract: agent_id, version, platform, architecture, config_schema.
    """
    return {
        "agent_id": agent_id,
        "version": version,
        "platform": platform.system() or "unknown",
        "architecture": platform.machine() or "unknown",
        "config_schema": {
            "telemetry": {
                "enabled": "boolean",
                "metrics": "object<string, boolean>",
                "interval_s": "integer (min: 1)",
                "change_threshold_percent": "number (min: 0)",
            },
            "heartbeat_s": "integer (min: 5, max: 3600)",
            "log_level": "string (enum: DEBUG, INFO, WARNING, ERROR, CRITICAL)",
        },
    }


def build_status(
    state: str,
    connected_since_ts: str,
    uptime_s: float | int,
) -> dict[str, Any]:
    """
    Build retained status. Contract: state, connected_since_ts, uptime_s.
    state: online | offline | error | starting
    """
    return {
        "state": state,
        "connected_since_ts": connected_since_ts,
        "uptime_s": uptime_s,
    }


def _system_cpu_percent() -> float:
    if psutil is None:
        return 0.0
    try:
        return float(psutil.cpu_percent(interval=None))
    except Exception:
        return 0.0


def _system_memory_percent() -> float:
    if psutil is None:
        return 0.0
    try:
        return float(psutil.virtual_memory().percent)
    except Exception:
        return 0.0


def _system_disk_percent() -> float:
    if psutil is None:
        return 0.0
    try:
        return float(psutil.disk_usage("/").percent)
    except Exception:
        return 0.0


def build_state(
    components_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Build retained state. Contract: cpu_percent, memory_percent, disk_percent, components.
    components: [ { component_id, version, enabled } ]
    """
    return {
        "cpu_percent": _system_cpu_percent(),
        "memory_percent": _system_memory_percent(),
        "disk_percent": _system_disk_percent(),
        "components": list(components_list),
    }


def build_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Build retained cfg. Contract: telemetry (nested), heartbeat_s, log_level.
    Ensures telemetry structure exists with defaults.
    """
    result = cfg.copy()
    
    # Ensure telemetry structure exists
    if "telemetry" not in result:
        result["telemetry"] = {}
    
    telemetry = result["telemetry"]
    if not isinstance(telemetry, dict):
        telemetry = {}
        result["telemetry"] = telemetry
    
    # Set defaults for telemetry if missing
    if "enabled" not in telemetry:
        telemetry["enabled"] = False
    if "metrics" not in telemetry:
        telemetry["metrics"] = {}
    if "interval_s" not in telemetry:
        telemetry["interval_s"] = 2
    if "change_threshold_percent" not in telemetry:
        telemetry["change_threshold_percent"] = 2.0
    
    return result
