"""
Validation constants and rules for the agent runtime configuration.

Pure functions — no I/O, no side effects. Safe to import anywhere.
"""

from __future__ import annotations

from typing import Any, Optional

ALLOWED_KEYS: dict[str, type] = {
    "telemetry": dict,
    "heartbeat_s": int,
    "log_level": str,
}

MIN_HEARTBEAT = 5
MAX_HEARTBEAT = 3600
DEFAULT_LOG_LEVEL = "INFO"
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
CFG_GENERAL_KEYS: set[str] = {"heartbeat_s"}
CFG_LOGGING_KEYS: set[str] = {"log_level"}


def validate(cfg: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Validate a configuration dict against allowed keys and per-key constraints.

    Returns (True, None) on success or (False, error_message) on failure.
    """
    if not isinstance(cfg, dict):
        return False, "config must be a dict"

    for key, value in cfg.items():
        if key not in ALLOWED_KEYS:
            return False, f"unknown config key: {key}"

        expected_type = ALLOWED_KEYS[key]
        if not isinstance(value, expected_type):
            return False, f"{key} must be {expected_type.__name__}, got {type(value).__name__}"

        if key == "telemetry":
            if "metrics" in value:
                if not isinstance(value["metrics"], dict):
                    return False, "telemetry.metrics must be a dict"
                for metric_name, metric_cfg in value["metrics"].items():
                    if not isinstance(metric_cfg, dict):
                        return False, f"telemetry.metrics.{metric_name} must be a dict"
                    if "enabled" in metric_cfg and not isinstance(metric_cfg["enabled"], bool):
                        return False, f"telemetry.metrics.{metric_name}.enabled must be boolean"
                    if "interval_s" in metric_cfg:
                        if not isinstance(metric_cfg["interval_s"], int) or metric_cfg["interval_s"] < 1:
                            return False, f"telemetry.metrics.{metric_name}.interval_s must be integer >= 1"
                    if "change_threshold_percent" in metric_cfg:
                        if (
                            not isinstance(metric_cfg["change_threshold_percent"], (int, float))
                            or metric_cfg["change_threshold_percent"] < 0
                        ):
                            return False, (
                                f"telemetry.metrics.{metric_name}.change_threshold_percent must be number >= 0"
                            )

        if key == "heartbeat_s":
            if not (MIN_HEARTBEAT <= value <= MAX_HEARTBEAT):
                return False, f"heartbeat_s must be between {MIN_HEARTBEAT} and {MAX_HEARTBEAT}"

        if key == "log_level":
            if value not in VALID_LOG_LEVELS:
                return False, f"log_level must be one of {VALID_LOG_LEVELS}"

    return True, None
