"""
ConfigStore — persistent runtime configuration with atomic writes and in-memory caching.

Config is stored at {base_dir}/data/core_config.json.
Load → validate → cache → serve from cache on subsequent reads.
Writes are atomic (temp + fsync + rename).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from lucid_agent_core.core.config._file_io import atomic_write, utc_iso
from lucid_agent_core.core.config._validation import (
    CFG_GENERAL_KEYS,
    CFG_LOGGING_KEYS,
    validate,
)
from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)


class ConfigStoreError(RuntimeError):
    """Raised when config store operations fail."""


class ConfigStore:
    """
    Persistent runtime configuration store with atomic writes and caching.

    Call load() once at startup. Subsequent reads use get_cached().
    All mutations go through apply_set_* which validate + save + update cache atomically.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        if path is None:
            self.path = get_paths().config_path
        else:
            self.path = Path(path)
        self._cache: Optional[dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Core I/O
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Load config from disk, validate, cache, and return it."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise ConfigStoreError(f"Permission denied creating {self.path.parent}") from exc

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

            ok, error = validate(data)
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
            raise ConfigStoreError(f"Failed to read {self.path}") from exc

    def save(self, cfg: dict[str, Any]) -> None:
        """Validate *cfg* and write it to disk atomically, updating the in-memory cache."""
        ok, error = validate(cfg)
        if not ok:
            raise ConfigStoreError(f"Invalid config: {error}")

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise ConfigStoreError(f"Permission denied creating {self.path.parent}") from exc

        try:
            atomic_write(self.path, cfg)
            self._cache = cfg
            logger.info("Saved config to %s", self.path)
        except Exception as exc:
            logger.exception("Failed to save config")
            raise ConfigStoreError(f"Failed to save config: {exc}") from exc

    def get_cached(self) -> dict[str, Any]:
        """Return a copy of the cached config without I/O. Call load() first."""
        if self._cache is None:
            logger.warning("get_cached() called before load(), returning empty dict")
            return {}
        return self._cache.copy()

    # ------------------------------------------------------------------
    # Apply helpers
    # ------------------------------------------------------------------

    def _extract_set_dict(
        self, payload: dict[str, Any]
    ) -> tuple[str, dict[str, Any], Optional[dict[str, Any]]]:
        ts = utc_iso()
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
        ts = utc_iso()
        current = self.get_cached()

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

        ok, validate_error = validate(new_cfg)
        if not ok:
            return current, {"request_id": request_id, "ok": False, "error": validate_error, "ts": ts}

        try:
            self.save(new_cfg)
        except ConfigStoreError as exc:
            return current, {"request_id": request_id, "ok": False, "error": str(exc), "ts": ts}

        applied = {k: set_dict[k] for k in set_dict if k in allowed_keys}
        return new_cfg, {"request_id": request_id, "ok": True, "applied": applied, "ts": ts}

    # ------------------------------------------------------------------
    # Domain-specific apply methods
    # ------------------------------------------------------------------

    def apply_set_general(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Apply cmd/cfg/set changes (heartbeat_s)."""
        return self._apply_top_level_keys(payload, allowed_keys=CFG_GENERAL_KEYS)

    def apply_set_logging(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Apply cmd/cfg/logging/set changes (log_level)."""
        return self._apply_top_level_keys(payload, allowed_keys=CFG_LOGGING_KEYS)

    def apply_set_telemetry(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Apply cmd/cfg/telemetry/set changes.

        Deep-merges per-metric values into telemetry.metrics.
        Each value in set_dict can be a bool (shorthand for {enabled}) or a full metric config dict.
        """
        request_id, set_dict, error = self._extract_set_dict(payload)
        if error is not None:
            return self.get_cached(), error
        ts = utc_iso()
        current = self.get_cached()
        new_cfg = current.copy()

        telemetry_obj = dict(current.get("telemetry") or {})
        metrics_obj = dict(telemetry_obj.get("metrics") or {})

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
            existing = dict(metrics_obj.get(metric_name) or {})
            metrics_obj[metric_name] = {**existing, **metric_cfg}

        telemetry_obj["metrics"] = metrics_obj
        new_cfg["telemetry"] = telemetry_obj

        ok, validate_error = validate(new_cfg)
        if not ok:
            return current, {"request_id": request_id, "ok": False, "error": validate_error, "ts": ts}

        try:
            self.save(new_cfg)
        except ConfigStoreError as exc:
            return current, {"request_id": request_id, "ok": False, "error": str(exc), "ts": ts}

        return new_cfg, {"request_id": request_id, "ok": True, "applied": set_dict, "ts": ts}
