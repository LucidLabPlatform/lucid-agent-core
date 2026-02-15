"""
Core command handlers for LUCID Agent Core.

Orchestration layer: parse → call business logic → publish events → update snapshots.

Handlers have signature: handler(ctx: CoreCommandContext, payload_str: str) -> None
They handle all MQTT publishing and state updates; business logic stays pure.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from lucid_agent_core.components.registry import load_registry
from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.core.component_installer import handle_install_component
from lucid_agent_core.core.component_uninstaller import handle_uninstall_component
from lucid_agent_core.core.restart import request_systemd_restart
from lucid_agent_core.core.snapshots import (
    build_core_cfg_state,
    build_core_components_snapshot,
    build_core_metadata,
    build_core_state,
)

logger = logging.getLogger(__name__)


def on_install(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle component install command.

    Flow:
        1. Call handle_install_component (business logic)
        2. Publish install_result event
        3. Update retained core/components snapshot
        4. If restart_required: flush publish, then restart
    """
    try:
        # Call business logic
        result = handle_install_component(payload_str)

        # Convert to dict for publishing
        result_dict = asdict(result)

        # Publish result event (non-retained)
        msg_info = ctx.publish(
            ctx.topics.core_evt_components_install_result(),
            result_dict,
            retain=False,
            qos=1,
        )

        # Update retained snapshot
        registry = load_registry()
        snapshot = build_core_components_snapshot(registry)
        ctx.publish(ctx.topics.core_components(), snapshot, retain=True, qos=1)

        logger.info(
            "Install result: ok=%s component=%s restart=%s",
            result.ok,
            result.component_id,
            result.restart_required,
        )

        # Handle restart if required
        if result.ok and result.restart_required:
            try:
                msg_info.wait_for_publish(timeout=2.0)
                logger.info("Install result published, requesting restart")
                request_systemd_restart(reason=f"component install: {result.component_id}")
            except Exception as exc:
                logger.error("Failed to wait for publish or restart: %s", exc)

    except Exception as exc:
        logger.exception("Unhandled error in on_install")
        # Try to extract request_id for error event
        try:
            payload = json.loads(payload_str)
            request_id = payload.get("request_id", "")
        except Exception:
            request_id = ""

        ctx.publish_error(
            ctx.topics.core_evt_components_install_result(),
            request_id,
            f"unhandled error: {exc}",
        )


def on_uninstall(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle component uninstall command.

    Flow:
        1. Call handle_uninstall_component (business logic)
        2. Publish uninstall_result event
        3. Update retained core/components snapshot
        4. If restart_required: flush publish, then restart
    """
    try:
        # Call business logic
        result = handle_uninstall_component(payload_str)

        # Convert to dict for publishing
        result_dict = asdict(result)

        # Publish result event (non-retained)
        msg_info = ctx.publish(
            ctx.topics.core_evt_components_uninstall_result(),
            result_dict,
            retain=False,
            qos=1,
        )

        # Update retained snapshot
        registry = load_registry()
        snapshot = build_core_components_snapshot(registry)
        ctx.publish(ctx.topics.core_components(), snapshot, retain=True, qos=1)

        logger.info(
            "Uninstall result: ok=%s component=%s noop=%s restart=%s",
            result.ok,
            result.component_id,
            result.noop,
            result.restart_required,
        )

        # Handle restart if required
        if result.ok and result.restart_required:
            try:
                msg_info.wait_for_publish(timeout=2.0)
                logger.info("Uninstall result published, requesting restart")
                request_systemd_restart(reason=f"component uninstall: {result.component_id}")
            except Exception as exc:
                logger.error("Failed to wait for publish or restart: %s", exc)

    except Exception as exc:
        logger.exception("Unhandled error in on_uninstall")
        # Try to extract request_id for error event
        try:
            payload = json.loads(payload_str)
            request_id = payload.get("request_id", "")
        except Exception:
            request_id = ""

        ctx.publish_error(
            ctx.topics.core_evt_components_uninstall_result(),
            request_id,
            f"unhandled error: {exc}",
        )


def on_refresh(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle refresh command.

    Rebuilds and republishes all retained snapshots.

    Flow:
        1. Parse request_id
        2. Rebuild all snapshots
        3. Publish each retained snapshot
        4. Publish refresh_result event
    """
    try:
        # Parse payload
        try:
            payload = json.loads(payload_str)
            request_id = payload.get("request_id", "")
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse refresh payload: %s", exc)
            ctx.publish_error(
                ctx.topics.core_evt_refresh_result(),
                "",
                f"invalid JSON: {exc}",
            )
            return

        # Rebuild and publish all retained snapshots
        snapshots_updated = []

        # metadata
        metadata = build_core_metadata(ctx.agent_id, ctx.agent_version)
        ctx.publish(ctx.topics.core_metadata(), metadata, retain=True, qos=1)
        snapshots_updated.append("metadata")

        # state
        state = build_core_state(ctx.agent_id)
        ctx.publish(ctx.topics.core_state(), state, retain=True, qos=1)
        snapshots_updated.append("state")

        # components
        registry = load_registry()
        components = build_core_components_snapshot(registry)
        ctx.publish(ctx.topics.core_components(), components, retain=True, qos=1)
        snapshots_updated.append("components")

        # cfg
        cfg = ctx.config_store.get_cached()
        cfg_state = build_core_cfg_state(cfg)
        ctx.publish(ctx.topics.core_cfg_state(), cfg_state, retain=True, qos=1)
        snapshots_updated.append("cfg")

        # Publish refresh result
        result = {
            "request_id": request_id,
            "ok": True,
            "snapshots_updated": snapshots_updated,
            "ts": ctx.now_ts(),
        }

        ctx.publish(ctx.topics.core_evt_refresh_result(), result, retain=False, qos=1)
        logger.info("Refresh completed, updated %d snapshots", len(snapshots_updated))

    except Exception as exc:
        logger.exception("Unhandled error in on_refresh")
        try:
            payload = json.loads(payload_str)
            request_id = payload.get("request_id", "")
        except Exception:
            request_id = ""

        ctx.publish_error(
            ctx.topics.core_evt_refresh_result(),
            request_id,
            f"unhandled error: {exc}",
        )


def on_cfg_set(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle config set command.

    Flow:
        1. Parse {request_id, set: {...}}
        2. Call config_store.apply_set()
        3. Publish cfg_set_result event
        4. ONLY if ok=True:
           - Update retained core/cfg/state
           - If heartbeat_s changed, update MQTT heartbeat
    """
    try:
        # Parse payload
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse cfg_set payload: %s", exc)
            ctx.publish_error(
                ctx.topics.core_evt_cfg_set_result(),
                "",
                f"invalid JSON: {exc}",
            )
            return

        # Apply config changes
        old_cfg = ctx.config_store.get_cached()
        new_cfg, result_dict = ctx.config_store.apply_set(payload)

        # Publish result event
        ctx.publish(ctx.topics.core_evt_cfg_set_result(), result_dict, retain=False, qos=1)

        # ONLY if successful: update retained state and heartbeat
        if result_dict.get("ok"):
            # Update retained cfg/state
            cfg_state = build_core_cfg_state(new_cfg)
            ctx.publish(ctx.topics.core_cfg_state(), cfg_state, retain=True, qos=1)

            # Update heartbeat if changed
            old_heartbeat = old_cfg.get("heartbeat_s")
            new_heartbeat = new_cfg.get("heartbeat_s")
            if new_heartbeat is not None and new_heartbeat != old_heartbeat:
                logger.info("Heartbeat changed from %s to %s", old_heartbeat, new_heartbeat)
                # MQTT client must implement set_heartbeat_interval
                if hasattr(ctx.mqtt, "set_heartbeat_interval"):
                    ctx.mqtt.set_heartbeat_interval(new_heartbeat)  # type: ignore
                else:
                    logger.warning("MQTT client does not support set_heartbeat_interval")

            logger.info("Config set succeeded: %s", result_dict.get("applied"))
        else:
            logger.warning("Config set failed: %s", result_dict.get("error"))

    except Exception as exc:
        logger.exception("Unhandled error in on_cfg_set")
        try:
            payload = json.loads(payload_str)
            request_id = payload.get("request_id", "")
        except Exception:
            request_id = ""

        ctx.publish_error(
            ctx.topics.core_evt_cfg_set_result(),
            request_id,
            f"unhandled error: {exc}",
        )
