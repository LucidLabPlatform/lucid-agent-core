"""Handler for cmd/components/uninstall → evt/components/uninstall/result."""

from __future__ import annotations

import logging
from dataclasses import asdict

from lucid_agent_core.components.registry import load_registry
from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.core.handlers._dedup import check_duplicate
from lucid_agent_core.core.handlers._parsing import parse_payload, request_id
from lucid_agent_core.core.restart import request_systemd_restart
from lucid_agent_core.core.snapshots import build_components_list, build_state
from lucid_agent_core.core.upgrade import handle_uninstall_component

logger = logging.getLogger(__name__)


def on_components_uninstall(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/components/uninstall → evt/components/uninstall/result.

    After uninstall: republishes retained state. If restart_required: flushes publish then restarts.
    """
    rid = request_id(payload_str)
    if check_duplicate(ctx, rid, ctx.topics.evt_components_result("uninstall")):
        return
    try:
        result = handle_uninstall_component(payload_str)
        result_dict = asdict(result)

        msg_info = ctx.publish(
            ctx.topics.evt_components_result("uninstall"), result_dict, retain=False, qos=1
        )

        registry = load_registry()
        components_list = build_components_list(registry, ctx.component_manager)
        ctx.publish(ctx.topics.state(), build_state(components_list), retain=True, qos=1)

        logger.info(
            "Uninstall result: ok=%s component=%s restart=%s",
            result.ok,
            result.component_id,
            result.restart_required,
        )

        if result.ok and result.restart_required:
            try:
                msg_info.wait_for_publish(timeout=2.0)
                logger.info("Uninstall result published, requesting restart")
                request_systemd_restart(reason=f"component uninstall: {result.component_id}")
            except Exception as exc:
                logger.error("Failed to wait for publish or restart: %s", exc)

    except Exception as exc:
        logger.exception("Unhandled error in on_components_uninstall")
        payload = parse_payload(payload_str)
        ctx.publish_result_error(
            ctx.topics.evt_components_result("uninstall"),
            payload.get("request_id", ""),
            f"unhandled error: {exc}",
        )
