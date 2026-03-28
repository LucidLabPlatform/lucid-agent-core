"""
Request-ID deduplication for MQTT command handlers.

Prevents replayed or retransmitted commands from being executed twice.
"""

from __future__ import annotations

import logging
import threading
from collections import deque

from lucid_agent_core.core.cmd_context import CoreCommandContext

logger = logging.getLogger(__name__)


_MAX_SEEN = 10_000


class _SeenRequestIds:
    """Thread-safe bounded set of recently seen request_ids.

    Evicts the oldest entry once the cap is reached so memory stays bounded
    on long-running agents. The default cap of 10 000 covers ~7 days of
    activity at 1 command/minute with comfortable headroom.
    """

    def __init__(self, maxsize: int = _MAX_SEEN) -> None:
        self._lock = threading.Lock()
        self._maxsize = maxsize
        self._queue: deque[str] = deque()  # ordered insertion; left = oldest
        self._seen: set[str] = set()

    def check_and_add(self, request_id: str) -> bool:
        """Return True if request_id was already seen (duplicate). Adds if new."""
        if not request_id:
            return False
        with self._lock:
            if request_id in self._seen:
                return True
            if len(self._queue) >= self._maxsize:
                oldest = self._queue.popleft()
                self._seen.discard(oldest)
            self._queue.append(request_id)
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
