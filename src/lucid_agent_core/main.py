"""
LUCID Agent Core entrypoint.

CLI:
  lucid-agent-core run             -> run agent (runtime mode)
  lucid-agent-core install-service -> install + enable systemd service (sudo; Linux systemd only)
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as pkg_version
from typing import Optional

from lucid_agent_core.components.context import ComponentContext
from lucid_agent_core.components.loader import load_components

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
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

    cfg = load_config()

    rt = Runtime(shutdown=threading.Event())
    _install_signal_handlers(rt)

    logger.info("============================================================")
    logger.info("LUCID Agent Core")
    logger.info("Version: %s", get_version_string())
    logger.info("Agent username: %s", cfg.agent_username)
    logger.info("============================================================")

    agent = AgentMQTTClient(
        cfg.mqtt_host,
        cfg.mqtt_port,
        cfg.agent_username,
        cfg.agent_password,
        cfg.agent_version,
        heartbeat_interval_s=int(cfg.agent_heartbeat_s) if str(cfg.agent_heartbeat_s).isdigit() else 0,
    )
    rt.agent = agent

    if not agent.connect():
        logger.error("MQTT connection failed")
        return 1

    # Load components (but do not pretend this is lifecycle-managed until you implement start/stop topics)
    context = ComponentContext.create(agent_id=cfg.agent_username, mqtt=agent, config=cfg)

    components, load_results = load_components(context)
    logger.info("Component load results: %s", [r.__dict__ for r in load_results])

    rt.components = components

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

    sub.add_parser(
        "install-service",
        help="Install and enable systemd service (requires sudo; Linux only)",
    )

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.cmd == "install-service":
        from lucid_agent_core.installer import install_service

        install_service()
        return

    if args.cmd == "run":
        raise SystemExit(run_agent())

    raise SystemExit(2)


if __name__ == "__main__":
    main()
