"""
Retained topic helpers — publish retained MQTT snapshots for the agent.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def publish_retained_state(
    ctx: Any,
    topics: Any,
    components_list: list[dict[str, Any]],
) -> None:
    """
    Publish retained state with the current components list.
    Call after load_components() so state.components is accurate.
    """
    from lucid_agent_core.core.snapshots import build_state

    state = build_state(components_list)
    ctx.publish(topics.state(), state, retain=True, qos=1)
    logger.info("Published retained state with %d components", len(components_list))


def publish_retained_refresh(
    ctx: Any,
    topics: Any,
    components_list: list[dict[str, Any]],
    connected_ts: Optional[float],
    connected_since_ts: Optional[str],
    version: str,
) -> None:
    """
    Republish all retained snapshots: metadata, status, state, cfg, cfg/logging, cfg/telemetry.
    Use after cmd/refresh to refresh topics without a restart.
    """
    from lucid_agent_core.core.snapshots import (
        build_metadata,
        build_status,
        build_state,
        build_cfg,
        build_cfg_logging,
        build_cfg_telemetry,
    )

    metadata = build_metadata(ctx.agent_id, version)
    ctx.publish(topics.metadata(), metadata, retain=True, qos=1)

    uptime_s = 0.0
    if connected_ts is not None:
        uptime_s = max(0.0, time.time() - connected_ts)
    status = build_status(
        "online",
        connected_since_ts or _utc_iso(),
        uptime_s,
    )
    ctx.publish(topics.status(), status, retain=True, qos=1)

    state = build_state(components_list)
    ctx.publish(topics.state(), state, retain=True, qos=1)

    raw_cfg = ctx.config_store.get_cached()
    ctx.publish(topics.cfg(), build_cfg(raw_cfg), retain=True, qos=1)
    ctx.publish(topics.cfg_logging(), build_cfg_logging(raw_cfg), retain=True, qos=1)
    ctx.publish(topics.cfg_telemetry(), build_cfg_telemetry(raw_cfg), retain=True, qos=1)
    logger.info(
        "Published retained refresh (metadata, status, state, cfg, cfg/logging, cfg/telemetry)"
    )
