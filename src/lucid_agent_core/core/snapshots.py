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
    Build retained metadata. Contract: agent_id, version, platform, architecture.
    """
    return {
        "agent_id": agent_id,
        "version": version,
        "platform": platform.system() or "unknown",
        "architecture": platform.machine() or "unknown",
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
    Build retained cfg. Always includes ALL configurable keys with current values or defaults.
    Contract: telemetry (nested with per-metric configs), heartbeat_s, log_level.
    """
    result = cfg.copy()
    
    # Ensure telemetry structure exists
    if "telemetry" not in result:
        result["telemetry"] = {}
    
    telemetry = result["telemetry"]
    if not isinstance(telemetry, dict):
        telemetry = {}
        result["telemetry"] = telemetry
    
    # Ensure metrics dict exists
    if "metrics" not in telemetry:
        telemetry["metrics"] = {}
    
    # Get available metrics from core state (cpu_percent, memory_percent, disk_percent)
    available_metrics = {"cpu_percent", "memory_percent", "disk_percent"}
    
    # Ensure all available metrics are in config with defaults
    for metric_name in available_metrics:
        if metric_name not in telemetry["metrics"]:
            telemetry["metrics"][metric_name] = {
                "enabled": False,
                "interval_s": 2,
                "change_threshold_percent": 2.0,
            }
        else:
            # Ensure metric config has all required fields
            metric_cfg = telemetry["metrics"][metric_name]
            if not isinstance(metric_cfg, dict):
                metric_cfg = {}
                telemetry["metrics"][metric_name] = metric_cfg
            if "enabled" not in metric_cfg:
                metric_cfg["enabled"] = False
            if "interval_s" not in metric_cfg:
                metric_cfg["interval_s"] = 2
            if "change_threshold_percent" not in metric_cfg:
                metric_cfg["change_threshold_percent"] = 2.0
    
    # Always include heartbeat_s with default if missing
    if "heartbeat_s" not in result:
        result["heartbeat_s"] = 30
    
    # Always include log_level with default if missing
    if "log_level" not in result:
        result["log_level"] = "INFO"
    
    # Always include logs_enabled with default if missing
    if "logs_enabled" not in result:
        result["logs_enabled"] = False
    
    return result
