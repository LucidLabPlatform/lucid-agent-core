"""Handlers for cmd/components/upgrade and cmd/core/upgrade."""

from __future__ import annotations

import logging
from dataclasses import asdict

from lucid_agent_core.components.registry import load_registry
from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.core.handlers._dedup import check_duplicate
from lucid_agent_core.core.handlers._parsing import parse_payload, request_id
from lucid_agent_core.core.handlers.refresh_handler import _publish_component_metadata
from lucid_agent_core.core.restart import request_systemd_restart
from lucid_agent_core.core.snapshots import build_components_list, build_state
from lucid_agent_core.core.upgrade import handle_component_upgrade, handle_core_upgrade

logger = logging.getLogger(__name__)


def on_components_upgrade(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/components/upgrade → evt/components/upgrade/result.

    Downloads wheel, verifies SHA256, upgrades venv, updates registry, then restarts.
    """
    rid = request_id(payload_str)
    if check_duplicate(ctx, rid, ctx.topics.evt_components_result("upgrade")):
        return
    try:
        result = handle_component_upgrade(payload_str)
        result_dict = asdict(result)

        msg_info = ctx.publish(
            ctx.topics.evt_components_result("upgrade"), result_dict, retain=False, qos=1
        )

        registry = load_registry()
        if result.ok:
            registry[result.component_id] = registry.get(result.component_id, {})
            registry[result.component_id]["version"] = result.version
        components_list = build_components_list(registry, ctx.component_manager)
        ctx.publish(ctx.topics.state(), build_state(components_list), retain=True, qos=1)

        if result.ok:
            _publish_component_metadata(ctx, result.component_id, result.version)
            logger.info("Republished component metadata with version %s", result.version)

        logger.info(
            "Component upgrade result: ok=%s component=%s version=%s restart=%s",
            result.ok,
            result.component_id,
            result.version,
            result.restart_required,
        )

        if result.ok and result.restart_required:
            try:
                msg_info.wait_for_publish(timeout=2.0)
                logger.info("Component upgrade result published, requesting restart")
                request_systemd_restart(
                    reason=f"component upgrade: {result.component_id} to {result.version}"
                )
            except Exception as exc:
                logger.error("Failed to wait for publish or restart: %s", exc)

    except Exception as exc:
        logger.exception("Unhandled error in on_components_upgrade")
        payload = parse_payload(payload_str)
        ctx.publish_result_error(
            ctx.topics.evt_components_result("upgrade"),
            payload.get("request_id", ""),
            f"unhandled error: {exc}",
        )


def on_core_upgrade(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/core/upgrade → evt/core/upgrade/result.

    Downloads wheel, verifies SHA256, upgrades venv, then restarts.
    """
    rid = request_id(payload_str)
    if check_duplicate(ctx, rid, ctx.topics.evt_result("core/upgrade")):
        return
    try:
        result = handle_core_upgrade(payload_str)
        result_dict = asdict(result)

        msg_info = ctx.publish(
            ctx.topics.evt_result("core/upgrade"), result_dict, retain=False, qos=1
        )

        logger.info(
            "Core upgrade result: ok=%s version=%s restart=%s",
            result.ok,
            result.version,
            result.restart_required,
        )

        if result.ok and result.restart_required:
            try:
                msg_info.wait_for_publish(timeout=2.0)
                logger.info("Core upgrade result published, requesting restart")
                request_systemd_restart(reason=f"core upgrade: {result.version}")
            except Exception as exc:
                logger.error("Failed to wait for publish or restart: %s", exc)

    except Exception as exc:
        logger.exception("Unhandled error in on_core_upgrade")
        payload = parse_payload(payload_str)
        ctx.publish_result_error(
            ctx.topics.evt_result("core/upgrade"),
            payload.get("request_id", ""),
            f"unhandled error: {exc}",
        )
