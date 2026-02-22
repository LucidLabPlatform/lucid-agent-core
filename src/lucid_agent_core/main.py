"""
LUCID Agent Core entrypoint.

CLI:
  lucid-agent-core run                      -> run agent (runtime mode)
  lucid-agent-core install-service          -> install + enable systemd service (sudo; Linux systemd only)
  lucid-agent-core install-led-strip-helper  -> install + start LED strip helper (sudo; run once on device after MQTT install)
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from dataclasses import asdict, dataclass, is_dataclass
from importlib.metadata import PackageNotFoundError, version as pkg_version
from typing import Optional

from lucid_component_base import ComponentContext
from lucid_agent_core.components.loader import load_components


def _configure_logging(cfg: dict | None = None) -> None:
    """
    Single log level for all scopes (core, base, components).
    Uses cfg["log_level"] if provided, else LUCID_LOG_LEVEL env, else INFO.
    """
    from lucid_agent_core.core.log_config import apply_log_level_from_config

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    apply_log_level_from_config(cfg)


_configure_logging()
logger = logging.getLogger(__name__)


def get_version_string() -> str:
    try:
        return pkg_version("lucid-agent-core")
    except PackageNotFoundError:
        return "0.0.0+dev"


@dataclass
class Runtime:
    shutdown: threading.Event
    agent: Optional[object] = None
    components: Optional[list[object]] = None


def _install_signal_handlers(rt: Runtime) -> None:
    def _handler(signum: int, frame) -> None:  # frame is unused, keep signature
        logger.info("Received signal %s; requesting shutdown", signum)
        rt.shutdown.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def run_agent() -> int:
    """
    Runtime mode: connect to MQTT, publish presence, load components, block until shutdown.
    Returns process exit code.
    """
    # Lazy imports keep install-service isolated from runtime env/config.
    from lucid_agent_core.mqtt_client import AgentMQTTClient
    from lucid_agent_core.config import load_config
    from lucid_agent_core.core.config_store import ConfigStore
    from lucid_agent_core.core.cmd_context import CoreCommandContext
    from lucid_agent_core.paths import get_paths, ensure_dirs

    # Ensure all directories exist
    paths = get_paths()
    ensure_dirs(paths)

    cfg = load_config()

    # 1. Load runtime config store and apply log level from cfg (or LUCID_LOG_LEVEL env)
    config_store = ConfigStore()
    runtime_cfg = config_store.load()
    heartbeat_s = runtime_cfg.get("heartbeat_s", cfg.agent_heartbeat_s)

    from lucid_agent_core.core.log_config import apply_log_level_from_config
    apply_log_level_from_config(runtime_cfg)

    logger.info("Runtime config loaded: %s", runtime_cfg)

    rt = Runtime(shutdown=threading.Event())
    _install_signal_handlers(rt)

    logger.info("============================================================")
    logger.info("LUCID Agent Core")
    logger.info("Version: %s", get_version_string())
    logger.info("Agent username: %s", cfg.agent_username)
    logger.info("============================================================")

    # 2. Create MQTT client with initial heartbeat
    agent = AgentMQTTClient(
        cfg.mqtt_host,
        cfg.mqtt_port,
        cfg.agent_username,
        cfg.agent_password,
        cfg.agent_version,
        heartbeat_interval_s=heartbeat_s,
    )
    rt.agent = agent

    # 3. Create command context
    ctx = CoreCommandContext(
        mqtt=agent,
        topics=agent.topics,
        agent_id=cfg.agent_username,
        agent_version=cfg.agent_version,
        config_store=config_store,
        component_manager=agent,  # AgentMQTTClient implements ComponentManager
    )

    # 4. Set context BEFORE connect
    agent.set_context(ctx)

    # 5. Connect (will publish snapshots in _on_connect)
    if not agent.connect():
        logger.error("MQTT connection failed")
        return 1

    # Wait for connection callback to complete before publishing populated state
    # This ensures the MQTT connection is fully established before we publish
    for _ in range(50):  # Wait up to 5 seconds
        if agent.is_connected():
            break
        time.sleep(0.1)
    else:
        logger.warning("Connection not established after 5 seconds, proceeding anyway")

    # Load components and register their cmd handlers + update state
    components, load_results = load_components(
        agent_id=cfg.agent_username,
        base_topic=agent.topics.base,
        mqtt=agent,
        config=cfg,
    )
    logger.info(
        "Component load results: %s",
        [asdict(r) if (is_dataclass(r) and not isinstance(r, type)) else repr(r) for r in load_results],
    )

    rt.components = components

    # Load registry for component state and gating
    from lucid_agent_core.components.registry import load_registry
    from lucid_agent_core.core.snapshots import build_components_list
    registry = load_registry()
    
    components_list = build_components_list(registry, components=components)
    agent.add_component_handlers(components, registry)
    agent.publish_retained_state(components_list)

    logger.info("Agent running (shutdown via SIGINT/SIGTERM)")

    try:
        while not rt.shutdown.is_set():
            time.sleep(0.5)
    finally:
        _shutdown(rt)

    return 0


def _shutdown(rt: Runtime) -> None:
    logger.info("Shutting down...")

    # Stop components first (they may depend on mqtt connection)
    if rt.components:
        for component in rt.components:
            try:
                component.stop()
            except Exception:
                logger.exception("Error stopping component")
        logger.info("Components stopped")

    if rt.agent:
        try:
            rt.agent.disconnect()
        except Exception:
            logger.exception("Error disconnecting MQTT")
        logger.info("MQTT disconnected")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lucid-agent-core")
    p.add_argument("--version", action="version", version=get_version_string())

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run", help="Run agent runtime")

    install_parser = sub.add_parser(
        "install-service",
        help="Install and enable systemd service (requires sudo; Linux only)",
    )
    install_parser.add_argument(
        "--wheel",
        type=str,
        metavar="PATH",
        help="Path to local wheel file (alternative to GitHub release download)",
    )

    sub.add_parser(
        "install-led-strip-helper",
        help="Install and start the LED strip helper daemon (requires sudo; run once on the device after MQTT install)",
    )

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.cmd == "install-service":
        from pathlib import Path
        from lucid_agent_core.installer import install_service

        wheel_path = Path(args.wheel) if args.wheel else None
        install_service(wheel_path)
        return

    if args.cmd == "install-led-strip-helper":
        from lucid_agent_core.installer import install_led_strip_helper

        install_led_strip_helper()
        return

    if args.cmd == "run":
        raise SystemExit(run_agent())

    raise SystemExit(2)


if __name__ == "__main__":
    main()
