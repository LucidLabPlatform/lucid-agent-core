"""
LUCID Agent Core
Connects to MQTT broker and publishes agent status.

CLI:
  lucid-agent-core                 -> run agent (runtime mode)
  lucid-agent-core install-service -> install + start systemd service (sudo; Linux systemd only)
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from importlib.metadata import PackageNotFoundError, version as pkg_version
from lucid_agent_core.components.loader import load_components
from lucid_agent_core.components.context import ComponentContext

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

agent = None
components = []


def get_version_string() -> str:
    try:
        return pkg_version("lucid-agent-core")
    except PackageNotFoundError:
        return "0.0.0+dev"


def _signal_handler(signum, frame):
    logger.info("Received signal %s, shutting down...", signum)
    global agent, components
    if components:
        for component in components:
            try:
                component.stop()
            except Exception:
                logger.exception("Error stopping component")
        logger.info("Components stopped")
    if agent:
        agent.disconnect()
    raise SystemExit(0)


def run_agent() -> None:
    """
    Runtime mode: connect to MQTT and publish status.

    Imports are inside the function so install-service can run without env vars.
    """
    global agent

    # Lazy imports keep install-service isolated from runtime config loading.
    from lucid_agent_core.mqtt_client import AgentMQTTClient
    from lucid_agent_core import config

    config.load_config()

    logger.info("=" * 60)
    logger.info("LUCID Agent Core")
    logger.info("=" * 60)
    logger.info("Username: %s", config.AGENT_USERNAME)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    agent = AgentMQTTClient(
        config.MQTT_HOST,
        config.MQTT_PORT,
        config.AGENT_USERNAME,
        config.AGENT_PASSWORD,
        config.AGENT_VERSION,
        config.AGENT_HEARTBEAT,
    )

    if not agent.connect():
        logger.error("Failed to connect to broker. Exiting.")
        raise SystemExit(1)

    time.sleep(1)

    if not agent.is_connected():
        logger.error("Agent failed to connect. Exiting.")
        raise SystemExit(1)

    logger.info("Agent is online and running. Ctrl+C to stop.")

    context = ComponentContext(
        agent_id=config.AGENT_USERNAME,
        mqtt_client=agent,
        config=config
    )

    global components
    components = load_components(context)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        _signal_handler(signal.SIGINT, None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lucid-agent-core")
    p.add_argument("--version", action="version", version=get_version_string())

    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("install-service", help="Install and start systemd service (requires sudo; Linux only)")

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.cmd == "install-service":
        # Install-service is intentionally isolated from runtime imports/config.
        from lucid_agent_core.installer import install_service

        install_service()
        return

    run_agent()


if __name__ == "__main__":
    main()
