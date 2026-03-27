"""
Core command handlers for LUCID Agent Core — unified v1.0.0 contract.

All on_* handler functions are re-exported here so call sites only need to
import from this package rather than from individual handler modules.
"""

from lucid_agent_core.core.handlers._dedup import _seen_request_ids
from lucid_agent_core.core.handlers.config_handlers import (
    on_cfg_logging_set,
    on_cfg_set,
    on_cfg_telemetry_set,
)
from lucid_agent_core.core.handlers.component_handlers import (
    on_components_disable,
    on_components_enable,
)
from lucid_agent_core.core.handlers.install_handler import on_components_install
from lucid_agent_core.core.handlers.ping_handler import on_ping
from lucid_agent_core.core.handlers.refresh_handler import on_refresh
from lucid_agent_core.core.handlers.restart_handler import on_restart
from lucid_agent_core.core.handlers.uninstall_handler import on_components_uninstall
from lucid_agent_core.core.handlers.upgrade_handler import on_components_upgrade, on_core_upgrade

__all__ = [
    # Dedup state (exposed for test fixtures: handlers._seen_request_ids._seen.clear())
    "_seen_request_ids",
    # Handler functions
    "on_ping",
    "on_restart",
    "on_refresh",
    "on_cfg_set",
    "on_cfg_logging_set",
    "on_cfg_telemetry_set",
    "on_components_enable",
    "on_components_disable",
    "on_components_install",
    "on_components_uninstall",
    "on_components_upgrade",
    "on_core_upgrade",
]
