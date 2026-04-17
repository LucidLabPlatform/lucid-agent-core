"""Handler for cmd/components/install → evt/components/install/result."""

from __future__ import annotations

import logging
from dataclasses import asdict

from lucid_agent_core.components.registry import load_registry
from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.core.handlers._dedup import check_duplicate
from lucid_agent_core.core.handlers._parsing import parse_payload, request_id
from lucid_agent_core.core.restart import request_systemd_restart
from lucid_agent_core.core.snapshots import build_components_list, build_state
from lucid_agent_core.core.upgrade import handle_install_component
from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)


def _try_install_led_strip_helper() -> None:
    """Log instructions for installing the LED strip helper daemon."""
    try:
        paths = get_paths()
        installer = paths.venv_dir / "bin" / "lucid-led-strip-helper-installer"
        if not installer.is_file():
            logger.debug(
                "led_strip helper installer not found at %s (install with [pi] extra?)", installer
            )
            return
        logger.info(
            "LED strip component installed. To start the helper daemon, run on the device: "
            "sudo %s install-led-strip-helper",
            str(paths.venv_dir / "bin" / "lucid-agent-core"),
        )
    except Exception as exc:
        logger.debug("Could not resolve path for led_strip helper hint: %s", exc)


def on_components_install(ctx: CoreCommandContext, payload_str: str) -> None:
    """
    Handle cmd/components/install → evt/components/install/result.

    After install: republishes retained state. If restart_required: flushes publish then restarts.
    """
    rid = request_id(payload_str)
    if check_duplicate(ctx, rid, ctx.topics.evt_components_result("install")):
        return
    try:
        result = handle_install_component(payload_str)
        result_dict = asdict(result)

        msg_info = ctx.publish(
            ctx.topics.evt_components_result("install"), result_dict, retain=False, qos=1
        )

        registry = load_registry()
        components_list = build_components_list(registry)
        ctx.publish(ctx.topics.state(), build_state(components_list), retain=True, qos=1)

        logger.info(
            "Install result: ok=%s component=%s restart=%s",
            result.ok,
            result.component_id,
            result.restart_required,
        )

        if result.ok and result.component_id == "led_strip":
            _try_install_led_strip_helper()

        if result.ok and result.restart_required:
            try:
                msg_info.wait_for_publish(timeout=2.0)
                logger.info("Install result published, requesting restart")
                request_systemd_restart(reason=f"component install: {result.component_id}")
            except Exception as exc:
                logger.error("Failed to wait for publish or restart: %s", exc)

    except Exception as exc:
        logger.exception("Unhandled error in on_components_install")
        payload = parse_payload(payload_str)
        ctx.publish_result_error(
            ctx.topics.evt_components_result("install"),
            payload.get("request_id", ""),
            f"unhandled error: {exc}",
        )
