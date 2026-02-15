"""
Component registry — persistent JSON store of installed components.

Path: {base_dir}/data/components_registry.json. Atomic writes with fsync.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lucid_agent_core.paths import get_paths


class RegistryError(RuntimeError):
    """Raised when registry operations fail in a non-recoverable way."""


def _fsync_dir(path: Path) -> None:
    """
    Ensure directory metadata is flushed so atomic rename is durable.
    """
    fd = os.open(str(path), os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _now_ts() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _validate_registry_shape(data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, dict):
            continue
        # Minimal sanity: keep only dict entries. Full schema validation can grow later.
        out[k] = v
    return out


def load_registry() -> dict[str, dict[str, Any]]:
    paths = get_paths()
    registry_path = paths.registry_path
    
    if not registry_path.exists():
        return {}

    try:
        with registry_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return _validate_registry_shape(data)
    except json.JSONDecodeError:
        # Preserve corrupted file for debugging instead of silently hiding it.
        corrupt = registry_path.with_suffix(f".corrupt.{_now_ts()}.json")
        try:
            registry_path.replace(corrupt)
        except Exception:
            # If we can't move it, we still fail soft and return empty.
            pass
        return {}
    except OSError as exc:
        raise RegistryError(f"failed to read registry: {exc}") from exc


def write_registry(data: dict[str, dict[str, Any]]) -> None:
    """
    Atomic, durable write:
    - lock
    - write temp file + fsync
    - replace
    - fsync directory
    """
    paths = get_paths()
    registry_path = paths.registry_path
    lock_path = paths.registry_lock_path
    
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    # Lazy import: only Linux has fcntl. Agent targets Linux primarily.
    import fcntl  # type: ignore

    with lock_path.open("w") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)

        cleaned = _validate_registry_shape(data)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(registry_path.parent),
        ) as tf:
            json.dump(cleaned, tf, indent=2, sort_keys=True)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_path = Path(tf.name)

        os.replace(tmp_path, registry_path)
        _fsync_dir(registry_path.parent)

        fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)


def is_same_install(existing: dict[str, Any] | None, repo: str, version: str, entrypoint: str) -> bool:
    if not isinstance(existing, dict):
        return False
    return (
        existing.get("repo") == repo
        and existing.get("version") == version
        and existing.get("entrypoint") == entrypoint
    )
