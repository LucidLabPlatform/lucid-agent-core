"""
Runtime configuration store for LUCID Agent Core.

Persistent storage at {base_dir}/data/core_config.json with atomic writes.
In-memory caching to avoid redundant I/O.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)


# Allowed configuration keys and their types/constraints
ALLOWED_KEYS = {
    "telemetry": dict,  # Nested: {enabled, metrics, interval_s, change_threshold_percent}
    "heartbeat_s": int,
    "log_level": str,
}

# Validation constraints
MIN_HEARTBEAT = 5
MAX_HEARTBEAT = 3600
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
CFG_GENERAL_KEYS = {"heartbeat_s"}
CFG_LOGGING_KEYS = {"log_level"}


class ConfigStoreError(RuntimeError):
    """Raised when config store operations fail."""


def _fsync_dir(path: Path) -> None:
    """Ensure directory metadata is flushed for durability."""
    fd = os.open(str(path), os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _utc_iso() -> str:
    """Return current UTC timestamp as ISO8601 string."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class ConfigStore:
    """
    Persistent runtime configuration store with atomic writes and caching.

    Config is stored at {base_dir}/data/core_config.json.
    Changes are validated and written atomically (temp + fsync + rename).
    """

    def __init__(self, path: Optional[str] = None) -> None:
        if path is None:
            paths = get_paths()
            self.path = paths.config_path
        else:
            self.path = Path(path)
        self._cache: Optional[dict[str, Any]] = None

    def load(self) -> dict[str, Any]:
        """
        Load configuration from disk.

        Creates parent directory if needed. Returns validated config or empty dict.
        Caches result in memory.

        Returns:
            Configuration dict (may be empty)

        Raises:
            ConfigStoreError: If directory creation fails with permissions error
        """
        # Ensure directory exists
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            logger.error("Cannot create config directory %s: %s", self.path.parent, exc)
            raise ConfigStoreError(f"Permission denied creating {self.path.parent}") from exc

        # Load existing config or return empty
        if not self.path.exists():
            logger.info("Config file not found, using defaults: %s", self.path)
            self._cache = {}
            return {}

        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning("Config file is not a dict, using defaults")
                self._cache = {}
                return {}

            # Validate and cache
            ok, error = self.validate(data)
            if not ok:
                logger.warning("Config validation failed: %s, using defaults", error)
                self._cache = {}
                return {}

            self._cache = data
            logger.info("Loaded config from %s: %s", self.path, data)
            return data

        except json.JSONDecodeError as exc:
            logger.error("Config file is corrupted: %s", exc)
            self._cache = {}
            return {}
        except OSError as exc:
            logger.error("Failed to read config: %s", exc)
            raise ConfigStoreError(f"Failed to read {self.path}") from exc

    def save(self, cfg: dict[str, Any]) -> None:
        """
        Save configuration to disk atomically.

        Updates cache on success.

        Args:
            cfg: Configuration dict to save

        Raises:
            ConfigStoreError: If validation fails or write fails
        """
        ok, error = self.validate(cfg)
        if not ok:
            raise ConfigStoreError(f"Invalid config: {error}")

        # Ensure directory exists
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise ConfigStoreError(f"Permission denied creating {self.path.parent}") from exc

        # Atomic write with fsync
        try:
            # Lazy import: only Linux has fcntl
            import fcntl  # type: ignore

            paths = get_paths()
            lock_path = paths.config_lock_path
            with lock_path.open("w") as lockf:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)

                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    delete=False,
                    dir=str(self.path.parent),
                ) as tf:
                    json.dump(cfg, tf, indent=2, sort_keys=True)
                    tf.flush()
                    os.fsync(tf.fileno())
                    tmp_path = Path(tf.name)

                os.replace(tmp_path, self.path)
                _fsync_dir(self.path.parent)

                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

            # Update cache
            self._cache = cfg
            logger.info("Saved config to %s", self.path)

        except Exception as exc:
            logger.exception("Failed to save config")
            raise ConfigStoreError(f"Failed to save config: {exc}") from exc

    def validate(self, cfg: dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate configuration keys and values.

        Args:
            cfg: Configuration dict to validate

        Returns:
            Tuple of (ok, error_message)
        """
        if not isinstance(cfg, dict):
            return False, "config must be a dict"

        for key, value in cfg.items():
            if key not in ALLOWED_KEYS:
                return False, f"unknown config key: {key}"

            expected_type = ALLOWED_KEYS[key]
            if not isinstance(value, expected_type):
                return False, f"{key} must be {expected_type.__name__}, got {type(value).__name__}"

            # Type-specific validation
            if key == "telemetry":
                if not isinstance(value, dict):
                    return False, "telemetry must be a dict"
                # Validate telemetry structure: metrics dict with per-metric configs
                if "metrics" in value:
                    if not isinstance(value["metrics"], dict):
                        return False, "telemetry.metrics must be a dict"
                    # Validate each metric config
                    for metric_name, metric_cfg in value["metrics"].items():
                        if not isinstance(metric_cfg, dict):
                            return False, f"telemetry.metrics.{metric_name} must be a dict"
                        if "enabled" in metric_cfg and not isinstance(metric_cfg["enabled"], bool):
                            return False, f"telemetry.metrics.{metric_name}.enabled must be boolean"
                        if "interval_s" in metric_cfg:
                            if (
                                not isinstance(metric_cfg["interval_s"], int)
                                or metric_cfg["interval_s"] < 1
                            ):
                                return (
                                    False,
                                    f"telemetry.metrics.{metric_name}.interval_s must be integer >= 1",
                                )
                        if "change_threshold_percent" in metric_cfg:
                            if (
                                not isinstance(metric_cfg["change_threshold_percent"], (int, float))
                                or metric_cfg["change_threshold_percent"] < 0
                            ):
                                return (
                                    False,
                                    f"telemetry.metrics.{metric_name}.change_threshold_percent must be number >= 0",
                                )

            if key == "heartbeat_s":
                if not (MIN_HEARTBEAT <= value <= MAX_HEARTBEAT):
                    return False, f"heartbeat_s must be between {MIN_HEARTBEAT} and {MAX_HEARTBEAT}"

            if key == "log_level":
                if value not in VALID_LOG_LEVELS:
                    return False, f"log_level must be one of {VALID_LOG_LEVELS}"

        return True, None

    def _extract_set_dict(
        self, payload: dict[str, Any]
    ) -> tuple[str, dict[str, Any], Optional[dict[str, Any]]]:
        ts = _utc_iso()
        request_id = payload.get("request_id", "")
        if "set" not in payload:
            return request_id, {}, {
                "request_id": request_id,
                "ok": False,
                "error": "missing 'set' field in payload",
                "ts": ts,
            }
        set_dict = payload["set"]
        if not isinstance(set_dict, dict):
            return request_id, {}, {
                "request_id": request_id,
                "ok": False,
                "error": "'set' must be a dict",
                "ts": ts,
            }
        return request_id, set_dict, None

    def _apply_top_level_keys(
        self, payload: dict[str, Any], *, allowed_keys: set[str]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        request_id, set_dict, error = self._extract_set_dict(payload)
        if error is not None:
            return self.get_cached(), error
        ts = _utc_iso()
        current = self.get_cached().copy()

        unknown = sorted(k for k in set_dict if k not in allowed_keys)
        if unknown:
            return current, {
                "request_id": request_id,
                "ok": False,
                "error": f"unknown config key(s): {', '.join(unknown)}",
                "ts": ts,
            }

        new_cfg = current.copy()
        for key in allowed_keys:
            if key in set_dict:
                new_cfg[key] = set_dict[key]

        ok, validate_error = self.validate(new_cfg)
        if not ok:
            return current, {
                "request_id": request_id,
                "ok": False,
                "error": validate_error,
                "ts": ts,
            }

        try:
            self.save(new_cfg)
        except ConfigStoreError as exc:
            return current, {
                "request_id": request_id,
                "ok": False,
                "error": str(exc),
                "ts": ts,
            }

        applied = {k: set_dict[k] for k in set_dict.keys() if k in allowed_keys}
        return new_cfg, {
            "request_id": request_id,
            "ok": True,
            "applied": applied,
            "ts": ts,
        }

    def apply_set_general(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Apply cfg/set changes (retained /cfg domain).

        Allowed keys: heartbeat_s.
        """
        return self._apply_top_level_keys(payload, allowed_keys=CFG_GENERAL_KEYS)

    def apply_set_logging(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Apply cfg/logging/set changes (retained /cfg/logging domain).

        Allowed keys: log_level.
        """
        return self._apply_top_level_keys(payload, allowed_keys=CFG_LOGGING_KEYS)

    def apply_set_telemetry(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Apply cfg/telemetry/set changes (retained /cfg/telemetry domain).

        Expects payload: {request_id, set: {metric_name: metric_cfg_or_enabled_bool}}
        where metric_cfg_or_enabled_bool is either:
        - {enabled?, interval_s?, change_threshold_percent?}
        - bool (shorthand for enabled)

        Deep-merges per-metric values into telemetry.metrics in the config store.
        """
        request_id, set_dict, error = self._extract_set_dict(payload)
        if error is not None:
            return self.get_cached(), error
        ts = _utc_iso()
        current = self.get_cached().copy()
        new_cfg = current.copy()

        telemetry_obj = current.get("telemetry", {})
        if not isinstance(telemetry_obj, dict):
            telemetry_obj = {}
        telemetry_obj = telemetry_obj.copy()

        metrics_obj = telemetry_obj.get("metrics", {})
        if not isinstance(metrics_obj, dict):
            metrics_obj = {}
        metrics_obj = metrics_obj.copy()

        for metric_name, metric_cfg in set_dict.items():
            if isinstance(metric_cfg, bool):
                metric_cfg = {"enabled": metric_cfg}
            if not isinstance(metric_cfg, dict):
                return current, {
                    "request_id": request_id,
                    "ok": False,
                    "error": f"telemetry metric '{metric_name}' must be an object or boolean",
                    "ts": ts,
                }
            existing = metrics_obj.get(metric_name, {})
            if not isinstance(existing, dict):
                existing = {}
            metrics_obj[metric_name] = {**existing, **metric_cfg}

        telemetry_obj["metrics"] = metrics_obj
        new_cfg["telemetry"] = telemetry_obj

        # Validate merged config
        ok, validate_error = self.validate(new_cfg)
        if not ok:
            return current, {
                "request_id": request_id,
                "ok": False,
                "error": validate_error,
                "ts": ts,
            }

        # Save atomically
        try:
            self.save(new_cfg)
        except ConfigStoreError as exc:
            return current, {
                "request_id": request_id,
                "ok": False,
                "error": str(exc),
                "ts": ts,
            }

        return new_cfg, {
            "request_id": request_id,
            "ok": True,
            "applied": set_dict,
            "ts": ts,
        }

    def get_cached(self) -> dict[str, Any]:
        """
        Return cached configuration without I/O.

        Must call load() first to populate cache.

        Returns:
            Cached configuration dict (may be empty)
        """
        if self._cache is None:
            logger.warning("get_cached() called before load(), returning empty dict")
            return {}
        return self._cache.copy()
