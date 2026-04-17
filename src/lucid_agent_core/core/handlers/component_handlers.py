"""Handlers for cmd/components/enable and cmd/components/disable."""

from __future__ import annotations

import logging

from lucid_agent_core.components.registry import load_registry, write_registry
from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.core.handlers._dedup import check_duplicate
from lucid_agent_core.core.handlers._parsing import parse_payload
from lucid_agent_core.core.snapshots import build_components_list, build_state

logger = logging.getLogger(__name__)


def on_components_enable(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/components/enable → evt/components/enable/result.

    Sets enabled=True in registry, starts the component if loaded, republishes state.
    """
    payload = parse_payload(payload_str)
    rid = payload.get("request_id", "")
    component_id = payload.get("component_id", "")

    if check_duplicate(ctx, rid, ctx.topics.evt_components_result("enable")):
        return

    if not component_id:
        ctx.publish_result_error(
            ctx.topics.evt_components_result("enable"), rid, "component_id is required"
        )
        return

    try:
        registry = load_registry()
        if component_id not in registry:
            ctx.publish_result_error(
                ctx.topics.evt_components_result("enable"),
                rid,
                f"component not found: {component_id}",
            )
            return

        registry[component_id]["enabled"] = True
        write_registry(registry)

        started = False
        if ctx.component_manager:
            started = ctx.component_manager.start_component(component_id, registry)
            if not started:
                logger.warning(
                    "Component %s enable: start_component returned False (component may not be loaded)",
                    component_id,
                )
        else:
            logger.warning("Component %s enable: component_manager not available", component_id)

        components_list = build_components_list(registry)
        ctx.publish(ctx.topics.state(), build_state(components_list), retain=True, qos=1)
        ctx.publish(
            ctx.topics.evt_components_result("enable"),
            {"request_id": rid, "ok": True, "error": None},
            retain=False,
            qos=1,
        )
        logger.info("Component enabled: %s (started=%s)", component_id, started)

    except Exception as exc:
        logger.exception("Error enabling component")
        ctx.publish_result_error(
            ctx.topics.evt_components_result("enable"), rid, f"error: {exc}"
        )


def on_components_disable(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/components/disable → evt/components/disable/result.

    Stops the component, sets enabled=False in registry, republishes state.
    """
    payload = parse_payload(payload_str)
    rid = payload.get("request_id", "")
    component_id = payload.get("component_id", "")

    if check_duplicate(ctx, rid, ctx.topics.evt_components_result("disable")):
        return

    if not component_id:
        ctx.publish_result_error(
            ctx.topics.evt_components_result("disable"), rid, "component_id is required"
        )
        return

    try:
        registry = load_registry()
        if component_id not in registry:
            ctx.publish_result_error(
                ctx.topics.evt_components_result("disable"),
                rid,
                f"component not found: {component_id}",
            )
            return

        stopped = False
        if ctx.component_manager:
            stopped = ctx.component_manager.stop_component(component_id)
            if stopped:
                logger.info("Stopped component: %s", component_id)

        registry[component_id]["enabled"] = False
        write_registry(registry)

        components_list = build_components_list(registry)
        ctx.publish(ctx.topics.state(), build_state(components_list), retain=True, qos=1)
        ctx.publish(
            ctx.topics.evt_components_result("disable"),
            {"request_id": rid, "ok": True, "error": None},
            retain=False,
            qos=1,
        )
        logger.info("Component disabled: %s (stopped=%s)", component_id, stopped)

    except Exception as exc:
        logger.exception("Error disabling component")
        ctx.publish_result_error(
            ctx.topics.evt_components_result("disable"), rid, f"error: {exc}"
        )
