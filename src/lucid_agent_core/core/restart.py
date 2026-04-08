from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)

# Debounce restarts to avoid loops (seconds)
_RESTART_DEBOUNCE_S = 10


def _is_managed() -> bool:
    """
    Best-effort check: running under a service manager (systemd or launchd).

    Detects:
    - systemd: INVOCATION_ID env var or /run/systemd/system exists
    - launchd: macOS with parent PID 1 (launched by launchd)
    - Explicit: LUCID_MANAGED env var set (works for any service manager)
    """
    if os.getenv("INVOCATION_ID"):
        return True
    if Path("/run/systemd/system").exists():
        return True
    if sys.platform == "darwin" and os.getppid() == 1:
        return True
    if os.getenv("LUCID_MANAGED"):
        return True
    return False


def request_systemd_restart(reason: str = "restart requested") -> bool:
    """
    Request restart by terminating the process.

    Returns:
      True if a restart signal was sent, False if suppressed or not safe.

    Safety behavior:
    - If not running under a managed environment, do not kill the process.
    - Debounce repeated restart requests.
    - Record the request to a sentinel file for observability.
    """
    if not _is_managed():
        logger.warning("Restart requested (%s) but service manager not detected; ignoring", reason)
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
        sentinel_path.write_text(
            f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))} {reason}\n"
        )

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
