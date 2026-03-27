"""
Request-ID deduplication for MQTT command handlers.

Prevents replayed or retransmitted commands from being executed twice.
"""

from __future__ import annotations

import logging
import threading

from lucid_agent_core.core.cmd_context import CoreCommandContext

logger = logging.getLogger(__name__)


class _SeenRequestIds:
    """Thread-safe set of all request_ids seen since agent start."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def check_and_add(self, request_id: str) -> bool:
        """Return True if request_id was already seen (duplicate). Adds to set if new."""
        if not request_id:
            return False
        with self._lock:
            if request_id in self._seen:
                return True
            self._seen.add(request_id)
            return False


_seen_request_ids = _SeenRequestIds()


def check_duplicate(ctx: CoreCommandContext, request_id: str, result_topic: str) -> bool:
    """Return True and publish an error if *request_id* was already seen. Caller should return early."""
    if _seen_request_ids.check_and_add(request_id):
        logger.warning("Duplicate request_id=%s rejected", request_id)
        ctx.publish(
            result_topic,
            {"request_id": request_id, "ok": False, "error": "duplicate request_id"},
            retain=False,
            qos=1,
        )
        return True
    return False
