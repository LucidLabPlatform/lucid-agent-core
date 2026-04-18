"""
Retained snapshot builders for LUCID Agent Core — unified v1.0.0 contract.

Pure functions that build MQTT retained payload dicts.
No schema versioning; no legacy fields.
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from typing import Any

from lucid_agent_core.core.config._validation import DEFAULT_LOG_LEVEL


def now_iso8601() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()


def build_metadata(version: str) -> dict[str, Any]:
    """
    Build retained metadata. Contract: version, platform, architecture.
    agent_id is carried by the topic path, not the payload.
    """
    return {
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


def build_components_list(
    registry: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Build components list for state topic.

    Returns:
        List of component dicts: [{component_id, version, enabled}]
    """
    return [
        {
            "component_id": cid,
            "version": meta.get("version", "?"),
            "enabled": meta.get("enabled", True),
        }
        for cid, meta in registry.items()
    ]


def build_state(
    components_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Build retained state. Contract: components.
    components: [ { component_id, version, enabled } ]
    System metrics (cpu, memory, disk) belong in telemetry, not state.
    """
    return {
        "components": list(components_list),
    }


def build_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Build retained cfg topic payload.
    Contract: general operational settings only — {heartbeat_s}.
    Logging settings → build_cfg_logging(). Telemetry settings → build_cfg_telemetry().
    """
    return {
        "heartbeat_s": int(cfg.get("heartbeat_s", 30)),
    }


def build_cfg_logging(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Build retained cfg/logging topic payload.
    Contract: {log_level}.
    """
    return {
        "log_level": str(cfg.get("log_level", DEFAULT_LOG_LEVEL)),
    }


def build_agent_schema() -> dict[str, Any]:
    """
    Build the agent-level MQTT topic schema.
    Describes every topic the agent publishes and subscribes to.
    """
    _telemetry_metric_cfg = {
        "type": "object",
        "fields": {
            "enabled": {"type": "boolean"},
            "interval_s": {"type": "integer", "min": 1},
            "change_threshold_percent": {"type": "float", "min": 0},
        },
    }
    return {
        "publishes": {
            "metadata": {
                "fields": {
                    "version": {"type": "string"},
                    "platform": {"type": "string"},
                    "architecture": {"type": "string"},
                },
            },
            "status": {
                "fields": {
                    "state": {"type": "string", "enum": ["online", "offline", "error", "starting"]},
                    "connected_since_ts": {"type": "string", "description": "ISO8601 UTC"},
                    "uptime_s": {"type": "float"},
                },
            },
            "state": {
                "fields": {
                    "components": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "fields": {
                                "component_id": {"type": "string"},
                                "version": {"type": "string"},
                                "enabled": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
            "cfg": {
                "fields": {
                    "heartbeat_s": {"type": "integer", "min": 5, "max": 3600},
                },
            },
            "cfg/logging": {
                "fields": {
                    "log_level": {"type": "string", "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]},
                },
            },
            "cfg/telemetry": {
                "fields": {
                    "cpu_percent": _telemetry_metric_cfg,
                    "memory_percent": _telemetry_metric_cfg,
                    "disk_percent": _telemetry_metric_cfg,
                },
            },
            "logs": {
                "fields": {
                    "level": {"type": "string", "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]},
                    "message": {"type": "string"},
                },
            },
            "telemetry/cpu_percent": {"fields": {"value": {"type": "float", "min": 0, "max": 100, "unit": "%"}}},
            "telemetry/memory_percent": {"fields": {"value": {"type": "float", "min": 0, "max": 100, "unit": "%"}}},
            "telemetry/disk_percent": {"fields": {"value": {"type": "float", "min": 0, "max": 100, "unit": "%"}}},
            "schema": {},
        },
        "subscribes": {
            "cmd/ping": {"fields": {}},
            "cmd/restart": {"fields": {}},
            "cmd/refresh": {"fields": {}},
            "cmd/cfg/set": {
                "fields": {
                    "set": {
                        "type": "object",
                        "fields": {
                            "heartbeat_s": {"type": "integer", "min": 5, "max": 3600},
                        },
                    },
                },
            },
            "cmd/cfg/logging/set": {
                "fields": {
                    "set": {
                        "type": "object",
                        "fields": {
                            "log_level": {"type": "string", "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]},
                        },
                    },
                },
            },
            "cmd/cfg/telemetry/set": {
                "fields": {
                    "set": {
                        "type": "object",
                        "description": "Per-metric config: {metric_name: {enabled, interval_s, change_threshold_percent}}",
                    },
                },
            },
            "cmd/components/install": {
                "fields": {
                    "component_id": {"type": "string"},
                    "source": {
                        "type": "object",
                        "fields": {
                            "type": {"type": "string", "enum": ["github_release"]},
                            "owner": {"type": "string"},
                            "repo": {"type": "string"},
                            "version": {"type": "string"},
                            "sha256": {"type": "string"},
                        },
                    },
                },
            },
            "cmd/components/uninstall": {
                "fields": {
                    "component_id": {"type": "string"},
                },
            },
            "cmd/components/enable": {
                "fields": {
                    "component_id": {"type": "string"},
                },
            },
            "cmd/components/disable": {
                "fields": {
                    "component_id": {"type": "string"},
                },
            },
            "cmd/components/upgrade": {
                "fields": {
                    "component_id": {"type": "string"},
                    "source": {
                        "type": "object",
                        "fields": {
                            "type": {"type": "string", "enum": ["github_release"]},
                            "owner": {"type": "string"},
                            "repo": {"type": "string"},
                            "version": {"type": "string"},
                            "sha256": {"type": "string"},
                        },
                    },
                },
            },
            "cmd/core/upgrade": {
                "fields": {
                    "source": {
                        "type": "object",
                        "fields": {
                            "type": {"type": "string", "enum": ["github_release"]},
                            "version": {"type": "string"},
                            "sha256": {"type": "string"},
                        },
                    },
                },
            },
        },
    }


def build_cfg_telemetry(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Build retained cfg/telemetry topic payload.
    Contract: flat metric dict — {metric_name: {enabled, interval_s, change_threshold_percent}}.
    No nested "metrics" wrapper. Always includes all 3 system metrics so the user can see
    what is available and toggle them on/off.
    """
    available_metrics = ["cpu_percent", "memory_percent", "disk_percent"]
    stored_metrics = cfg.get("telemetry", {}).get("metrics", {})

    result: dict[str, Any] = {}
    for metric_name in available_metrics:
        metric_cfg = stored_metrics.get(metric_name, {})
        if not isinstance(metric_cfg, dict):
            metric_cfg = {}
        result[metric_name] = {
            "enabled": bool(metric_cfg.get("enabled", False)),
            "interval_s": int(metric_cfg.get("interval_s", 2)),
            "change_threshold_percent": float(metric_cfg.get("change_threshold_percent", 2.0)),
        }
    return result
