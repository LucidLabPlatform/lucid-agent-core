"""
Core command handlers for LUCID Agent Core — unified v1.0.0 contract.

Commands: cmd/ping, cmd/restart, cmd/refresh, cmd/cfg/set, cmd/components/{install,uninstall,enable,disable,upgrade}, cmd/core/upgrade.
Results: evt/<action>/result with { request_id, ok, error }.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

from lucid_agent_core.components.registry import load_registry, write_registry
from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.core.component_installer import handle_install_component
from lucid_agent_core.core.component_uninstaller import handle_uninstall_component
from lucid_agent_core.core.component_upgrader import handle_component_upgrade
from lucid_agent_core.core.core_upgrader import handle_core_upgrade
from lucid_agent_core.core.log_config import apply_log_level_from_config
from lucid_agent_core.core.restart import request_systemd_restart
from lucid_agent_core.core.snapshots import build_state

logger = logging.getLogger(__name__)


def _request_id(payload_str: str) -> str:
    try:
        payload = json.loads(payload_str) if payload_str else {}
        return payload.get("request_id", "")
    except json.JSONDecodeError:
        return ""


def _parse_payload(payload_str: str) -> dict:
    try:
        return json.loads(payload_str) if payload_str else {}
    except json.JSONDecodeError:
        return {}


def on_ping(ctx: CoreCommandContext, payload_str: str) -> None:
    """Handle cmd/ping → evt/ping/result."""
    request_id = _request_id(payload_str)
    ctx.publish_result("ping", request_id, ok=True, error=None)
    logger.debug("Ping result published for request_id=%s", request_id)


def on_restart(ctx: CoreCommandContext, payload_str: str) -> None:
    """Handle cmd/restart → evt/restart/result; then request process restart."""
    request_id = _request_id(payload_str)
    ok = request_systemd_restart(reason="cmd/restart")
    ctx.publish_result("restart", request_id, ok=ok, error=None if ok else "restart not available")
    if ok:
        logger.info("Restart requested for request_id=%s", request_id)


def on_refresh(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/refresh → evt/refresh/result.
    Republish retained topics that are not always updated: metadata, status, state, cfg.
    """
    request_id = _request_id(payload_str)
    try:
        registry = load_registry()
        from lucid_agent_core.core.snapshots import build_components_list, build_metadata, build_state, build_cfg
        components_list = build_components_list(registry, ctx.component_manager)
        if hasattr(ctx.mqtt, "publish_retained_refresh"):
            ctx.mqtt.publish_retained_refresh(components_list)
        else:
            state = build_state(components_list)
            ctx.publish(ctx.topics.metadata(), build_metadata(ctx.agent_id, ctx.agent_version), retain=True, qos=1)
            ctx.publish(ctx.topics.state(), state, retain=True, qos=1)
            cfg = ctx.config_store.get_cached()
            ctx.publish(ctx.topics.cfg(), build_cfg(cfg), retain=True, qos=1)
        ctx.publish_result("refresh", request_id, ok=True, error=None)
        logger.info("Refresh completed for request_id=%s", request_id)
    except Exception as exc:
        logger.exception("Refresh failed: %s", exc)
        ctx.publish_result("refresh", request_id, ok=False, error=str(exc))


def on_components_install(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/components/install → evt/components/install/result.
    
    After install: update state.components and republish retained state.
    If restart_required: flush publish, then restart.
    """
    try:
        result = handle_install_component(payload_str)
        result_dict = asdict(result)
        
        # Publish result
        msg_info = ctx.publish(
            ctx.topics.evt_components_result("install"),
            result_dict,
            retain=False,
            qos=1,
        )
        
        # Update retained state
        registry = load_registry()
        from lucid_agent_core.core.snapshots import build_components_list
        components_list = build_components_list(registry, ctx.component_manager)
        state = build_state(components_list)
        ctx.publish(ctx.topics.state(), state, retain=True, qos=1)
        
        logger.info(
            "Install result: ok=%s component=%s restart=%s",
            result.ok,
            result.component_id,
            result.restart_required,
        )
        
        if result.ok and result.restart_required:
            try:
                msg_info.wait_for_publish(timeout=2.0)
                logger.info("Install result published, requesting restart")
                request_systemd_restart(reason=f"component install: {result.component_id}")
            except Exception as exc:
                logger.error("Failed to wait for publish or restart: %s", exc)
    
    except Exception as exc:
        logger.exception("Unhandled error in on_components_install")
        payload = _parse_payload(payload_str)
        request_id = payload.get("request_id", "")
        ctx.publish_result_error(
            ctx.topics.evt_components_result("install"),
            request_id,
            f"unhandled error: {exc}",
        )


def on_components_uninstall(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/components/uninstall → evt/components/uninstall/result.
    
    After uninstall: update state.components and republish retained state.
    If restart_required: flush publish, then restart.
    """
    try:
        result = handle_uninstall_component(payload_str)
        result_dict = asdict(result)
        
        # Publish result
        msg_info = ctx.publish(
            ctx.topics.evt_components_result("uninstall"),
            result_dict,
            retain=False,
            qos=1,
        )
        
        # Update retained state
        registry = load_registry()
        from lucid_agent_core.core.snapshots import build_components_list
        components_list = build_components_list(registry, ctx.component_manager)
        state = build_state(components_list)
        ctx.publish(ctx.topics.state(), state, retain=True, qos=1)
        
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
        payload = _parse_payload(payload_str)
        request_id = payload.get("request_id", "")
        ctx.publish_result_error(
            ctx.topics.evt_components_result("uninstall"),
            request_id,
            f"unhandled error: {exc}",
        )


def on_components_enable(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/components/enable → evt/components/enable/result.
    
    Set enabled=true in registry, start component if loaded, resubscribe to topics, republish state.
    """
    payload = _parse_payload(payload_str)
    request_id = payload.get("request_id", "")
    component_id = payload.get("component_id", "")
    
    if not component_id:
        ctx.publish_result_error(
            ctx.topics.evt_components_result("enable"),
            request_id,
            "component_id is required",
        )
        return
    
    try:
        registry = load_registry()
        if component_id not in registry:
            ctx.publish_result_error(
                ctx.topics.evt_components_result("enable"),
                request_id,
                f"component not found: {component_id}",
            )
            return
        
        registry[component_id]["enabled"] = True
        write_registry(registry)
        
        # Try to start component if loaded (will resubscribe automatically)
        started = False
        if ctx.component_manager:
            started = ctx.component_manager.start_component(component_id, registry)
            if not started:
                logger.warning("Component %s enable: start_component returned False (component may not be loaded)", component_id)
        else:
            logger.warning("Component %s enable: component_manager not available", component_id)
        
        # Republish state
        from lucid_agent_core.core.snapshots import build_components_list
        components_list = build_components_list(registry, ctx.component_manager)
        state = build_state(components_list)
        ctx.publish(ctx.topics.state(), state, retain=True, qos=1)
        
        # Publish result
        result = {"request_id": request_id, "ok": True, "error": None}
        ctx.publish(ctx.topics.evt_components_result("enable"), result, retain=False, qos=1)
        
        logger.info("Component enabled: %s (started=%s)", component_id, started)
    
    except Exception as exc:
        logger.exception("Error enabling component")
        ctx.publish_result_error(
            ctx.topics.evt_components_result("enable"),
            request_id,
            f"error: {exc}",
        )


def on_components_disable(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/components/disable → evt/components/disable/result.
    
    Set enabled=false in registry, stop component, unsubscribe from topics, republish state.
    """
    payload = _parse_payload(payload_str)
    request_id = payload.get("request_id", "")
    component_id = payload.get("component_id", "")
    
    if not component_id:
        ctx.publish_result_error(
            ctx.topics.evt_components_result("disable"),
            request_id,
            "component_id is required",
        )
        return
    
    try:
        registry = load_registry()
        if component_id not in registry:
            ctx.publish_result_error(
                ctx.topics.evt_components_result("disable"),
                request_id,
                f"component not found: {component_id}",
            )
            return
        
        # Stop component if running
        stopped = False
        if ctx.component_manager:
            stopped = ctx.component_manager.stop_component(component_id)
            if stopped:
                logger.info("Stopped component: %s", component_id)
        
        registry[component_id]["enabled"] = False
        write_registry(registry)
        
        # Republish state
        from lucid_agent_core.core.snapshots import build_components_list
        components_list = build_components_list(registry, ctx.component_manager)
        state = build_state(components_list)
        ctx.publish(ctx.topics.state(), state, retain=True, qos=1)
        
        # Publish result
        result = {"request_id": request_id, "ok": True, "error": None}
        ctx.publish(ctx.topics.evt_components_result("disable"), result, retain=False, qos=1)
        
        logger.info("Component disabled: %s (stopped=%s)", component_id, stopped)
    
    except Exception as exc:
        logger.exception("Error disabling component")
        ctx.publish_result_error(
            ctx.topics.evt_components_result("disable"),
            request_id,
            f"error: {exc}",
        )


def on_cfg_set(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/cfg/set: merge payload["set"] into config, save, republish cfg, apply log_level.
    Result on evt/cfg/set/result.
    """
    try:
        payload = _parse_payload(payload_str)
    except Exception:
        payload = {}
    request_id = payload.get("request_id", "")

    new_cfg, result = ctx.config_store.apply_set(payload)
    result["request_id"] = request_id

    if result.get("ok"):
        apply_log_level_from_config(new_cfg)
        from lucid_agent_core.core.snapshots import build_cfg
        ctx.publish(ctx.topics.cfg(), build_cfg(new_cfg), retain=True, qos=1)
        # Telemetry thread will pick up config changes automatically

    topic = ctx.topics.evt_result("cfg/set")
    ctx.publish(topic, result, retain=False, qos=1)
    if result.get("ok"):
        logger.info("Config updated via cmd/cfg/set, log_level applied")
    else:
        logger.warning("Config set failed: %s", result.get("error"))


def on_components_upgrade(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/components/upgrade → evt/components/upgrade/result.

    Downloads wheel, verifies SHA256, upgrades venv, updates registry, then restarts.
    Same pattern as core upgrade.
    """
    try:
        result = handle_component_upgrade(payload_str)
        result_dict = asdict(result)

        # Publish result
        msg_info = ctx.publish(
            ctx.topics.evt_components_result("upgrade"),
            result_dict,
            retain=False,
            qos=1,
        )

        # Update retained state
        registry = load_registry()
        from lucid_agent_core.core.snapshots import build_components_list
        components_list = build_components_list(registry, ctx.component_manager)
        state = build_state(components_list)
        ctx.publish(ctx.topics.state(), state, retain=True, qos=1)

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
                request_systemd_restart(reason=f"component upgrade: {result.component_id} to {result.version}")
            except Exception as exc:
                logger.error("Failed to wait for publish or restart: %s", exc)

    except Exception as exc:
        logger.exception("Unhandled error in on_components_upgrade")
        payload = _parse_payload(payload_str)
        request_id = payload.get("request_id", "")
        ctx.publish_result_error(
            ctx.topics.evt_components_result("upgrade"),
            request_id,
            f"unhandled error: {exc}",
        )


def on_core_upgrade(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/core/upgrade → evt/core/upgrade/result.

    Downloads wheel, verifies SHA256, upgrades venv, then restarts.
    """
    try:
        result = handle_core_upgrade(payload_str)
        result_dict = asdict(result)

        # Publish result
        msg_info = ctx.publish(
            ctx.topics.evt_result("core/upgrade"),
            result_dict,
            retain=False,
            qos=1,
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
        payload = _parse_payload(payload_str)
        request_id = payload.get("request_id", "")
        ctx.publish_result_error(
            ctx.topics.evt_result("core/upgrade"),
            request_id,
            f"unhandled error: {exc}",
        )
