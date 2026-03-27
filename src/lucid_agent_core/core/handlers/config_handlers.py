"""Handlers for cfg/set, cfg/logging/set, and cfg/telemetry/set commands."""

from __future__ import annotations

import logging

from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.core.handlers._dedup import check_duplicate
from lucid_agent_core.core.handlers._parsing import parse_payload
from lucid_agent_core.core.log_config import apply_log_level_from_config
from lucid_agent_core.core.snapshots import build_cfg, build_cfg_logging, build_cfg_telemetry

logger = logging.getLogger(__name__)


def on_cfg_set(ctx: CoreCommandContext, payload_str: str) -> None:
    """Handle cmd/cfg/set — update general config and republish /cfg."""
    payload = parse_payload(payload_str)
    rid = payload.get("request_id", "")

    if check_duplicate(ctx, rid, ctx.topics.evt_result("cfg/set")):
        return

    new_cfg, result = ctx.config_store.apply_set_general(payload)
    result["request_id"] = rid

    if result.get("ok"):
        ctx.publish(ctx.topics.cfg(), build_cfg(new_cfg), retain=True, qos=1)
        if "heartbeat_s" in new_cfg:
            ctx.mqtt.set_heartbeat_interval(int(new_cfg["heartbeat_s"]))

    ctx.publish(ctx.topics.evt_result("cfg/set"), result, retain=False, qos=1)
    if result.get("ok"):
        logger.info("Config updated via cmd/cfg/set")
    else:
        logger.warning("Config set failed: %s", result.get("error"))


def on_cfg_logging_set(ctx: CoreCommandContext, payload_str: str) -> None:
    """Handle cmd/cfg/logging/set — update log level and republish /cfg/logging."""
    payload = parse_payload(payload_str)
    rid = payload.get("request_id", "")

    if check_duplicate(ctx, rid, ctx.topics.evt_result("cfg/logging/set")):
        return

    new_cfg, result = ctx.config_store.apply_set_logging(payload)
    result["request_id"] = rid

    if result.get("ok"):
        apply_log_level_from_config(new_cfg)
        ctx.publish(ctx.topics.cfg_logging(), build_cfg_logging(new_cfg), retain=True, qos=1)

    ctx.publish(ctx.topics.evt_result("cfg/logging/set"), result, retain=False, qos=1)
    if result.get("ok"):
        logger.info("Config updated via cmd/cfg/logging/set")
    else:
        logger.warning("Config logging set failed: %s", result.get("error"))


def on_cfg_telemetry_set(ctx: CoreCommandContext, payload_str: str) -> None:
    """Handle cmd/cfg/telemetry/set — update telemetry config and republish /cfg/telemetry."""
    payload = parse_payload(payload_str)
    rid = payload.get("request_id", "")

    if check_duplicate(ctx, rid, ctx.topics.evt_result("cfg/telemetry/set")):
        return

    new_cfg, result = ctx.config_store.apply_set_telemetry(payload)
    result["request_id"] = rid

    if result.get("ok"):
        ctx.publish(ctx.topics.cfg_telemetry(), build_cfg_telemetry(new_cfg), retain=True, qos=1)

    ctx.publish(ctx.topics.evt_result("cfg/telemetry/set"), result, retain=False, qos=1)
    if result.get("ok"):
        logger.info("Config updated via cmd/cfg/telemetry/set")
    else:
        logger.warning("Config telemetry set failed: %s", result.get("error"))
