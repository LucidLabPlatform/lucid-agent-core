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

from lucid_agent_core.components.loader import load_components
from lucid_agent_core.config import AgentConfig
from lucid_agent_core.core.config import ConfigStore

_CONNECT_TIMEOUT_S = 5.0
_CONNECT_POLL_INTERVAL_S = 0.1


def _configure_logging(cfg: dict | None = None) -> None:
    """
    Single log level for all scopes (core, base, components).
    Uses cfg["log_level"] if provided, else LUCID_LOG_LEVEL env, else INFO.
    """
    from lucid_agent_core.core.log_config import apply_log_level

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    apply_log_level(cfg)


logger = logging.getLogger(__name__)


def get_version_string() -> str:
    try:
        return pkg_version("lucid-agent-core")
    except PackageNotFoundError:
        return "0.0.0+dev"


@dataclass
class Runtime:
    shutdown: threading.Event
    agent: object
    components: Optional[list[object]] = None


def _install_signal_handlers(rt: Runtime) -> None:
    def _handler(signum: int, frame) -> None:  # frame is unused, keep signature
        logger.info("Received signal %s; requesting shutdown", signum)
        rt.shutdown.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


@dataclass
class _Bootstrap:
    app_cfg: AgentConfig
    config_store: ConfigStore
    runtime_cfg: dict
    heartbeat_s: float


def _bootstrap() -> _Bootstrap:
    """Load config, set up paths, configure logging. Call once at startup."""
    from lucid_agent_core.config import load_config
    from lucid_agent_core.paths import get_paths, ensure_dirs

    paths = get_paths()
    ensure_dirs(paths)

    app_cfg = load_config()
    store = ConfigStore()
    runtime_cfg = store.load()
    _configure_logging(runtime_cfg)
    logger.info("Runtime config loaded: %s", runtime_cfg)

    heartbeat_s = runtime_cfg.get("heartbeat_s", app_cfg.agent_heartbeat_s)
    return _Bootstrap(app_cfg=app_cfg, config_store=store, runtime_cfg=runtime_cfg, heartbeat_s=heartbeat_s)


def _connect_and_wait(agent: object, timeout_s: float = _CONNECT_TIMEOUT_S) -> bool:
    """Connect MQTT and poll until connected or timeout. Returns False on connect failure."""
    if not agent.connect():  # type: ignore[attr-defined]
        logger.error("MQTT connection failed")
        return False

    for _ in range(int(timeout_s / _CONNECT_POLL_INTERVAL_S)):
        if agent.is_connected():  # type: ignore[attr-defined]
            break
        time.sleep(_CONNECT_POLL_INTERVAL_S)
    else:
        logger.warning(
            "Connection not established after %.1f seconds, proceeding anyway", timeout_s
        )
    return True


def _load_and_start_components(
    agent: object,
    app_cfg: object,
) -> list[object]:
    """Load components from registry, register cmd handlers, publish retained state."""
    from lucid_agent_core.components.registry import load_registry
    from lucid_agent_core.core.snapshots import build_components_list

    components, load_results = load_components(
        agent_id=app_cfg.agent_username,  # type: ignore[attr-defined]
        base_topic=agent.topics.base,  # type: ignore[attr-defined]
        mqtt=agent,
    )
    logger.info(
        "Component load results: %s",
        [
            asdict(r) if (is_dataclass(r) and not isinstance(r, type)) else repr(r)
            for r in load_results
        ],
    )

    registry = load_registry()
    components_list = build_components_list(registry)
    agent.add_component_handlers(components, registry)  # type: ignore[attr-defined]
    agent.publish_retained_state(components_list)  # type: ignore[attr-defined]
    return components


def run_agent() -> int:
    """
    Runtime mode: connect to MQTT, publish presence, load components, block until shutdown.
    Returns process exit code.
    """
    from lucid_agent_core.mqtt import AgentMQTTClient
    from lucid_agent_core.core.cmd_context import CoreCommandContext

    boot = _bootstrap()

    logger.info("============================================================")
    logger.info("LUCID Agent Core")
    logger.info("Version: %s", get_version_string())
    logger.info("Agent username: %s", boot.app_cfg.agent_username)
    logger.info("============================================================")

    agent = AgentMQTTClient(
        boot.app_cfg.mqtt_host,
        boot.app_cfg.mqtt_port,
        boot.app_cfg.agent_username,
        boot.app_cfg.agent_password,
        boot.app_cfg.agent_version,
        heartbeat_interval_s=boot.heartbeat_s,
    )

    rt = Runtime(shutdown=threading.Event(), agent=agent)
    _install_signal_handlers(rt)

    ctx = CoreCommandContext(
        mqtt=agent,
        topics=agent.topics,
        agent_id=boot.app_cfg.agent_username,
        agent_version=boot.app_cfg.agent_version,
        config_store=boot.config_store,
        component_manager=agent,
    )
    agent.set_context(ctx)

    if not _connect_and_wait(agent):
        return 1

    rt.components = _load_and_start_components(agent, boot.app_cfg)

    logger.info("Agent running (shutdown via SIGINT/SIGTERM)")
    try:
        while not rt.shutdown.is_set():
            time.sleep(0.5)
    finally:
        _shutdown(rt)

    return 0


def _shutdown(rt: Runtime) -> None:
    logger.info("Shutting down...")

    if rt.components:
        for component in rt.components:
            try:
                component.stop(final=True)
            except TypeError:
                # Older component-base builds don't accept the final kwarg yet
                try:
                    component.stop()
                except Exception:
                    logger.exception("Error stopping component")
            except Exception:
                logger.exception("Error stopping component")
        logger.info("Components stopped")

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
