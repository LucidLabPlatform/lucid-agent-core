"""Handler for cmd/restart → evt/restart/result."""

from __future__ import annotations

import logging

from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.core.handlers._dedup import check_duplicate
from lucid_agent_core.core.handlers._parsing import request_id
from lucid_agent_core.core.restart import request_systemd_restart

logger = logging.getLogger(__name__)


def on_restart(ctx: CoreCommandContext, payload_str: str) -> None:
    """Handle cmd/restart → evt/restart/result; then request process restart."""
    rid = request_id(payload_str)
    logger.info("cmd/restart received request_id=%s", rid)
    if check_duplicate(ctx, rid, ctx.topics.evt_result("restart")):
        return
    ok = request_systemd_restart(reason="cmd/restart")
    ctx.publish_result("restart", rid, ok=ok, error=None if ok else "restart not available")
    if ok:
        logger.info("Restart requested for request_id=%s", rid)
