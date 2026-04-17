"""Handler for cmd/refresh → evt/refresh/result."""

from __future__ import annotations

import logging

from lucid_agent_core.components.registry import load_registry
from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.core.handlers._dedup import check_duplicate
from lucid_agent_core.core.handlers._parsing import request_id
from lucid_agent_core.core.snapshots import (
    build_cfg,
    build_cfg_logging,
    build_cfg_telemetry,
    build_components_list,
    build_metadata,
    build_state,
)

logger = logging.getLogger(__name__)


def _publish_component_metadata(
    ctx: CoreCommandContext, component_id: str, version: str
) -> None:
    """Publish retained metadata for one component."""
    meta: dict = {"component_id": component_id, "version": version, "capabilities": []}
    if ctx.component_manager:
        comp = ctx.component_manager.get_component(component_id)
        if comp and hasattr(comp, "capabilities") and callable(comp.capabilities):
            meta["capabilities"] = comp.capabilities()
    try:
        ctx.publish(ctx.topics.component_metadata(component_id), meta, retain=True, qos=1)
    except Exception as exc:
        logger.warning("Failed to publish component metadata for %s: %s", component_id, exc)


def on_refresh(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/refresh → evt/refresh/result.

    Republishes all retained topics and each component's metadata.
    """
    rid = request_id(payload_str)
    if check_duplicate(ctx, rid, ctx.topics.evt_result("refresh")):
        return
    try:
        registry = load_registry()
        components_list = build_components_list(registry)

        if hasattr(ctx.mqtt, "publish_retained_refresh"):
            ctx.mqtt.publish_retained_refresh(components_list)
        else:
            state = build_state(components_list)
            ctx.publish(
                ctx.topics.metadata(),
                build_metadata(ctx.agent_version),
                retain=True,
                qos=1,
            )
            ctx.publish(ctx.topics.state(), state, retain=True, qos=1)
            raw_cfg = ctx.config_store.get_cached()
            ctx.publish(ctx.topics.cfg(), build_cfg(raw_cfg), retain=True, qos=1)
            ctx.publish(ctx.topics.cfg_logging(), build_cfg_logging(raw_cfg), retain=True, qos=1)
            ctx.publish(ctx.topics.cfg_telemetry(), build_cfg_telemetry(raw_cfg), retain=True, qos=1)

        for cid, meta in registry.items():
            _publish_component_metadata(ctx, cid, meta.get("version", "?"))

        ctx.publish_result("refresh", rid, ok=True, error=None)
        logger.info("Refresh completed for request_id=%s", rid)
    except Exception as exc:
        logger.exception("Refresh failed: %s", exc)
        ctx.publish_result("refresh", rid, ok=False, error=str(exc))
