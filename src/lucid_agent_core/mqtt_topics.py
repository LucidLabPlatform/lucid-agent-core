"""
MQTT Topic Schema for LUCID Agent Core.

This module is the single source of truth for topic construction.
It implements the Agent Core topic model and component topic model.

Reference:
- LUCID internal topic model: lucid/agents/<username>/core/* and /components/<id>/*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Conservative: allow only what you can safely embed in MQTT paths.
# If you later want hyphens, add '-' explicitly.
_AGENT_ID_RE = re.compile(r"^[a-z0-9_]+$")
_COMPONENT_ID_RE = re.compile(r"^[a-z0-9_]+$") 
class TopicSchemaError(ValueError):
    """Raised when an invalid identifier is used to construct topics."""


def _validate_agent_username(agent_username: str) -> str:
    if not isinstance(agent_username, str) or not agent_username:
        raise TopicSchemaError("agent_username must be a non-empty string")
    if not _AGENT_ID_RE.fullmatch(agent_username):
        raise TopicSchemaError(
            f"agent_username '{agent_username}' is invalid; allowed: [a-z0-9_]+"
        )
    return agent_username


def _validate_component_id(component_id: str) -> str:
    if not isinstance(component_id, str) or not component_id:
        raise TopicSchemaError("component_id must be a non-empty string")
    if not _COMPONENT_ID_RE.fullmatch(component_id):
        raise TopicSchemaError(
            f"component_id '{component_id}' is invalid; allowed: [a-z0-9_]+"
        )
    return component_id


@dataclass(frozen=True, slots=True)
class TopicSchema:
    """
    MQTT topic schema for a single agent.

    All topics are rooted at:
      lucid/agents/<agent_username>
    """

    agent_username: str

    def __post_init__(self) -> None:
        _validate_agent_username(self.agent_username)

    @property
    def base(self) -> str:
        return f"lucid/agents/{self.agent_username}"

    # -------------------------
    # Agent presence (retained)
    # -------------------------
    def status(self) -> str:
        return f"{self.base}/status"

    # -------------------------
    # Core retained snapshots
    # -------------------------
    def core_metadata(self) -> str:
        return f"{self.base}/core/metadata"

    def core_state(self) -> str:
        return f"{self.base}/core/state"

    def core_components(self) -> str:
        return f"{self.base}/core/components"

    # -------------------------
    # Core command/event roots
    # -------------------------
    def core_cmd_root(self) -> str:
        return f"{self.base}/core/cmd"

    def core_evt_root(self) -> str:
        return f"{self.base}/core/evt"

    def core_log_root(self) -> str:
        return f"{self.base}/core/log"

    def core_cfg_root(self) -> str:
        return f"{self.base}/core/cfg"

    # -------------------------
    # Core concrete commands
    # -------------------------
    def core_cmd_refresh(self) -> str:
        return f"{self.base}/core/cmd/refresh"

    def core_cmd_components_install(self) -> str:
        return f"{self.base}/core/cmd/components/install"

    def core_cmd_components_uninstall(self) -> str:
        return f"{self.base}/core/cmd/components/uninstall"

    # -------------------------
    # Core concrete events
    # -------------------------
    def core_evt_refresh_result(self) -> str:
        return f"{self.base}/core/evt/refresh_result"

    def core_evt_components_install_result(self) -> str:
        return f"{self.base}/core/evt/components/install_result"

    def core_evt_components_uninstall_result(self) -> str:
        return f"{self.base}/core/evt/components/uninstall_result"

    def core_evt_cfg_set_result(self) -> str:
        return f"{self.base}/core/evt/cfg_set_result"

    # -------------------------
    # Core config pattern
    # -------------------------
    def core_cfg_state(self) -> str:
        return f"{self.base}/core/cfg/state"

    def core_cfg_set(self) -> str:
        return f"{self.base}/core/cfg/set"

    # -------------------------
    # Component topics
    # -------------------------
    def component_base(self, component_id: str) -> str:
        component_id = _validate_component_id(component_id)
        return f"{self.base}/components/{component_id}"

    def component_cmd_root(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/cmd"

    def component_evt_root(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/evt"

    def component_metadata(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/metadata"

    def component_state(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/state"

    def component_cfg_root(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/cfg"

    # Concrete component commands/events
    def component_cmd_start(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/cmd/start"

    def component_cmd_stop(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/cmd/stop"

    def component_evt_start_result(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/evt/start_result"

    def component_evt_stop_result(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/evt/stop_result"

    def component_evt_telemetry(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/evt/telemetry"

    # Config pattern
    def component_cfg_state(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/cfg/state"

    def component_cfg_set(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/cfg/set"

    def component_evt_cfg_set_result(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/evt/cfg_set_result"
