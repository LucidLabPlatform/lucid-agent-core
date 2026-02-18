"""
Apply log level from runtime config or env.

Single log level for all scopes (core, base, components).
Config (cfg topic / core_config.json) takes precedence over LUCID_LOG_LEVEL env.
"""

from __future__ import annotations

import logging
import os
from typing import Any


def _parse_level(raw: str) -> int:
    if not raw or not str(raw).strip():
        return logging.INFO
    raw = str(raw).strip().upper()
    if raw.isdigit():
        return int(raw)
    return int(getattr(logging, raw, logging.INFO))


def level_from_cfg_or_env(cfg: dict[str, Any] | None) -> int:
    """
    Resolve log level: cfg["log_level"] if present and valid, else LUCID_LOG_LEVEL env, else INFO.
    """
    if cfg and isinstance(cfg.get("log_level"), str):
        return _parse_level(cfg["log_level"])
    raw = os.environ.get("LUCID_LOG_LEVEL", "").strip()
    return _parse_level(raw) if raw else logging.INFO


def apply_log_level(level: int) -> None:
    """Set root logger level so all loggers (core, base, components) use this level."""
    root = logging.getLogger()
    root.setLevel(level)


def apply_log_level_from_config(cfg: dict[str, Any] | None) -> None:
    """
    Resolve level from config (or env) and apply to root logger.
    Call at startup and after cfg is updated via cmd/cfg/set.
    """
    level = level_from_cfg_or_env(cfg)
    apply_log_level(level)
