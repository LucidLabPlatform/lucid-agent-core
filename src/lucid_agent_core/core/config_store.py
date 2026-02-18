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
    "telemetry_enabled": bool,
    "heartbeat_s": int,
    "log_level": str,
}

# Validation constraints
MIN_HEARTBEAT = 5
MAX_HEARTBEAT = 3600
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


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
            if key == "heartbeat_s":
                if not (MIN_HEARTBEAT <= value <= MAX_HEARTBEAT):
                    return False, f"heartbeat_s must be between {MIN_HEARTBEAT} and {MAX_HEARTBEAT}"

            if key == "log_level":
                if value not in VALID_LOG_LEVELS:
                    return False, f"log_level must be one of {VALID_LOG_LEVELS}"

        return True, None

    def apply_set(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Apply configuration changes from a set command.

        Expects payload: {request_id, set: {...}}
        Validates, merges with current config, saves atomically.

        Args:
            payload: Command payload with request_id and set dict

        Returns:
            Tuple of (new_config, result_dict)
            result_dict contains: {request_id, ok, applied, error?, ts, schema}
        """
        ts = _utc_iso()
        request_id = payload.get("request_id", "")

        # Extract set dict
        if "set" not in payload:
            return self.get_cached(), {
                "request_id": request_id,
                "ok": False,
                "error": "missing 'set' field in payload",
                "ts": ts,
            }

        set_dict = payload["set"]
        if not isinstance(set_dict, dict):
            return self.get_cached(), {
                "request_id": request_id,
                "ok": False,
                "error": "'set' must be a dict",
                "ts": ts,
            }

        # Merge with current config
        current = self.get_cached().copy()
        new_cfg = {**current, **set_dict}

        # Validate merged config
        ok, error = self.validate(new_cfg)
        if not ok:
            return current, {
                "request_id": request_id,
                "ok": False,
                "error": error,
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
