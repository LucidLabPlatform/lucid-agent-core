from __future__ import annotations

import logging
import os
import signal

logger = logging.getLogger(__name__)


def request_systemd_restart(reason: str = "component install") -> None:
    """
    Restart the service WITHOUT calling systemctl.

    Why:
      - This process runs as an unprivileged user (e.g., 'lucid').
      - Calling `systemctl restart ...` will fail (no permission).
      - With systemd `Restart=always`, exiting the process triggers a restart.

    How:
      - Send SIGTERM to the current PID.
      - Your existing signal handler performs a clean shutdown (MQTT offline, disconnect, etc.).
      - systemd relaunches the service.
    """
    pid = os.getpid()
    logger.info("Restart requested (%s). Sending SIGTERM to pid=%s", reason, pid)
    os.kill(pid, signal.SIGTERM)