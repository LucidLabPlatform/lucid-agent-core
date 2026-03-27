"""
Heartbeat loop — publishes retained status on a fixed interval.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class StatusPayload:
    state: str
    connected_since_ts: str
    uptime_s: float

    def to_json(self) -> str:
        return json.dumps(
            {
                "state": self.state,
                "connected_since_ts": self.connected_since_ts,
                "uptime_s": self.uptime_s,
            }
        )


class HeartbeatLoop:
    """
    Publishes a retained status message on a configurable interval.

    Args:
        paho_publish:       The paho client's publish method.
        status_topic:       The MQTT topic to publish status to.
        get_connection_info: Callable returning (connected_since_ts, connected_ts) or None
                             if not connected.
    """

    def __init__(
        self,
        paho_publish: Callable[..., Any],
        status_topic: str,
        get_connection_info: Callable[[], Optional[tuple[str, float]]],
    ) -> None:
        self._paho_publish = paho_publish
        self._status_topic = status_topic
        self._get_connection_info = get_connection_info
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._interval_lock = threading.Lock()
        self._interval_s: int = 0

    def start(self, interval_s: int) -> None:
        """Start the heartbeat thread with the given interval (in seconds)."""
        if self._thread:
            return
        with self._interval_lock:
            self._interval_s = interval_s
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="mqtt-heartbeat")
        self._thread.start()

    def stop(self) -> None:
        """Stop the heartbeat thread and wait for it to exit."""
        if not self._thread:
            return
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        self._thread = None

    def update_interval(self, interval_s: int) -> None:
        """Update the heartbeat interval without restarting the thread."""
        with self._interval_lock:
            self._interval_s = interval_s

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            with self._interval_lock:
                interval = self._interval_s
            if interval <= 0:
                break
            if self._stop_event.wait(timeout=interval):
                break
            info = self._get_connection_info()
            if info is None:
                continue
            connected_since_ts, connected_ts = info
            try:
                uptime_s = max(0.0, time.time() - connected_ts)
                payload = StatusPayload(
                    state="online",
                    connected_since_ts=connected_since_ts,
                    uptime_s=uptime_s,
                )
                self._paho_publish(
                    self._status_topic,
                    payload=payload.to_json(),
                    qos=1,
                    retain=True,
                )
            except Exception as exc:
                logger.error("Heartbeat publish failed: %s", exc)
