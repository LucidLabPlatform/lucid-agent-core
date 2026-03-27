"""
Atomic file-write helpers for the config store.

All functions deal purely with file I/O — no validation or business logic.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def fsync_dir(path: Path) -> None:
    """Flush directory metadata to disk for write durability."""
    fd = os.open(str(path), os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def utc_iso() -> str:
    """Return the current UTC time as an ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path: Path, cfg: dict) -> None:
    """
    Write *cfg* to *path* atomically using a temp file, fsync, and rename.

    Acquires an exclusive fcntl lock on a companion .lock file during the write
    so concurrent processes see a consistent file.
    """
    import fcntl  # noqa: PLC0415 — Linux/macOS only; imported lazily

    lock_path = path.parent / (path.name + ".lock")
    with lock_path.open("w") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
        ) as tf:
            json.dump(cfg, tf, indent=2, sort_keys=True)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_path = Path(tf.name)

        os.replace(tmp_path, path)
        fsync_dir(path.parent)
        fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
