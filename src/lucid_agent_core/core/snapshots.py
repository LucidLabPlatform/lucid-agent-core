"""
Retained snapshot builders for LUCID Agent Core.

Pure functions that build MQTT retained payload dicts.
No I/O, no side effects, fully deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def now_iso8601() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()


def build_status_payload(state: str, version: str, agent_id: str) -> dict[str, Any]:
    """
    Build retained status payload.

    Args:
        state: "online" or "offline"
        version: Agent version string
        agent_id: Agent username/identifier

    Returns:
        Dict with state, version, agent_id, and timestamp
    """
    return {
        "state": state,
        "version": version,
        "agent_id": agent_id,
        "ts": now_iso8601(),
    }


def build_core_metadata(agent_id: str, version: str) -> dict[str, Any]:
    """
    Build core metadata snapshot.

    Args:
        agent_id: Agent username/identifier
        version: Agent version string

    Returns:
        Dict with agent_id, version, and timestamp
    """
    return {
        "agent_id": agent_id,
        "version": version,
        "ts": now_iso8601(),
    }


def build_core_state(agent_id: str, uptime_s: Optional[int] = None) -> dict[str, Any]:
    """
    Build core state snapshot.

    Args:
        agent_id: Agent username/identifier
        uptime_s: Optional uptime in seconds

    Returns:
        Dict with state, uptime_s (if provided), agent_id, and timestamp
    """
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "state": "running",
        "ts": now_iso8601(),
    }
    if uptime_s is not None:
        payload["uptime_s"] = uptime_s
    return payload


def build_core_components_snapshot(registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """
    Build core components snapshot from registry.

    Args:
        registry: Components registry dict (component_id -> metadata)

    Returns:
        Dict with count, components dict, and timestamp
    """
    return {
        "count": len(registry),
        "components": registry,
        "ts": now_iso8601(),
    }


def build_core_cfg_state(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Build core config state snapshot.

    Args:
        cfg: Runtime configuration dict

    Returns:
        Dict with cfg and timestamp
    """
    return {
        "cfg": cfg,
        "ts": now_iso8601(),
    }

