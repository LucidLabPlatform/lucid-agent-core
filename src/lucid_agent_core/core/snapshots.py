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


def build_cfg_telemetry(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Build retained cfg/telemetry. Contract: enabled, metrics, interval_s, change_threshold_percent.
    """
    return {
        "enabled": cfg.get("enabled", False),
        "metrics": dict(cfg.get("metrics", {})),
        "interval_s": int(cfg.get("interval_s", 2)),
        "change_threshold_percent": float(cfg.get("change_threshold_percent", 2.0)),
    }
