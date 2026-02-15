from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)

# Debounce restarts to avoid loops (seconds)
_RESTART_DEBOUNCE_S = 10


def _is_systemd_like() -> bool:
    """
    Best-effort check: under systemd, INVOCATION_ID is often present and/or
    we have a systemd runtime directory. This is not perfect, but it prevents
    accidental kills in dev.
    """
    if os.getenv("INVOCATION_ID"):
        return True
    return Path("/run/systemd/system").exists()


def request_systemd_restart(reason: str = "restart requested") -> bool:
    """
    Request restart by terminating the process.

    Returns:
      True if a restart signal was sent, False if suppressed or not safe.

    Safety behavior:
    - If not running under systemd-like environment, do not kill the process.
    - Debounce repeated restart requests.
    - Record the request to a sentinel file for observability.
    """
    if not _is_systemd_like():
        logger.warning("Restart requested (%s) but systemd not detected; ignoring", reason)
        return False

    paths = get_paths()
    sentinel_path = paths.restart_sentinel_path
    now = time.time()

    try:
        if sentinel_path.exists():
            last = sentinel_path.stat().st_mtime
            if now - last < _RESTART_DEBOUNCE_S:
                logger.warning(
                    "Restart requested (%s) but debounced (last %.1fs ago)",
                    reason,
                    now - last,
                )
                return False

        sentinel_path.parent.mkdir(parents=True, exist_ok=True)
        sentinel_path.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))} {reason}\n")

    except Exception:
        # Sentinel failure should not prevent restart.
        logger.exception("Failed to write restart sentinel")

    pid = os.getpid()
    logger.info("Restart requested (%s). Sending SIGTERM to pid=%s", reason, pid)

    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        logger.exception("Failed to send SIGTERM for restart request")
        return False
