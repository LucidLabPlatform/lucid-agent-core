"""Handler for cmd/ping → evt/ping/result."""

from __future__ import annotations

import logging

from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.core.handlers._dedup import check_duplicate
from lucid_agent_core.core.handlers._parsing import request_id

logger = logging.getLogger(__name__)


def on_ping(ctx: CoreCommandContext, payload_str: str) -> None:
    """Handle cmd/ping → evt/ping/result."""
    rid = request_id(payload_str)
    logger.debug("cmd/ping received request_id=%s", rid)
    if check_duplicate(ctx, rid, ctx.topics.evt_result("ping")):
        return
    ctx.publish_result("ping", rid, ok=True, error=None)
    logger.debug("Ping result published for request_id=%s", rid)
