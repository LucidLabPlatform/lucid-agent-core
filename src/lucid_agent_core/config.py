"""
Agent Core configuration.

Single source for runtime configuration. Values come from environment variables,
optionally loaded from standard env files.

Priority (lowest -> highest):
1) /etc/lucid/agent-core.env (system install)
2) ~/.config/lucid-agent-core/.env (user install)
3) ./.env (project override)
4) process environment variables (always win)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Iterable, Optional


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


def _package_version() -> str:
    try:
        return _pkg_version("lucid-agent-core")
    except PackageNotFoundError:
        return "0.0.0+dev"


def _env_paths() -> Iterable[Path]:
    # 1) system install
    yield Path("/etc/lucid/agent-core.env")

    # 2) user config dir
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    yield base / "lucid-agent-core" / ".env"

    # 3) project override
    yield Path(".env")


def _require_env(key: str) -> str:
    v = os.getenv(key)
    if v is None or v == "":
        raise ConfigError(f"Missing required environment variable: {key}")
    return v


def _parse_int(key: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Invalid integer for {key}: {raw!r}") from exc


@dataclass(frozen=True, slots=True)
class AgentConfig:
    mqtt_host: str
    mqtt_port: int
    agent_username: str
    agent_password: str
    agent_version: str
    agent_heartbeat_s: int  # 0 disables periodic refresh


def load_config(*, dotenv_enabled: bool = True) -> AgentConfig:
    """
    Load config by reading env files (if python-dotenv is installed) and then
    validating required environment variables.

    Returns an immutable AgentConfig. Raises ConfigError on failure.
    """
    if dotenv_enabled:
        try:
            from dotenv import load_dotenv  # type: ignore
        except Exception:
            load_dotenv = None  # type: ignore

        if load_dotenv is not None:
            for p in _env_paths():
                if p.is_file():
                    # do not override existing env vars; later files can fill missing
                    load_dotenv(p, override=False)

            # final pass: allow local .env to override explicitly if desired
            # (but keep process env highest priority anyway)
            if Path(".env").is_file():
                load_dotenv(Path(".env"), override=True)

    mqtt_host = _require_env("MQTT_HOST")
    mqtt_port = _parse_int("MQTT_PORT", _require_env("MQTT_PORT"))
    if not (1 <= mqtt_port <= 65535):
        raise ConfigError(f"MQTT_PORT out of range: {mqtt_port}")

    agent_username = _require_env("AGENT_USERNAME")
    agent_password = _require_env("AGENT_PASSWORD")

    heartbeat_raw = os.getenv("AGENT_HEARTBEAT", "0")
    heartbeat_s = _parse_int("AGENT_HEARTBEAT", heartbeat_raw)
    if heartbeat_s < 0:
        raise ConfigError("AGENT_HEARTBEAT must be >= 0 (0 disables)")

    return AgentConfig(
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        agent_username=agent_username,
        agent_password=agent_password,
        agent_version=_package_version(),
        agent_heartbeat_s=heartbeat_s,
    )
