"""
MQTT Topic Schema for LUCID Agent Core — unified v1.0.0 contract.

All topics under lucid/agents/<agent_id>/.
Agent retained: metadata, status, state, cfg, cfg/telemetry.
Agent stream: logs, telemetry/<metric>.
Agent commands: cmd/ping, cmd/restart, cmd/reset.
Agent results: evt/<action>/result.
Component topics: components/<component_id>/...
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_AGENT_ID_RE = re.compile(r"^[a-z0-9_]+$")
_COMPONENT_ID_RE = re.compile(r"^[a-z0-9_]+$")


class TopicSchemaError(ValueError):
    """Raised when an invalid identifier is used to construct topics."""


def _validate_agent_id(agent_id: str) -> str:
    if not isinstance(agent_id, str) or not agent_id:
        raise TopicSchemaError("agent_id must be a non-empty string")
    if not _AGENT_ID_RE.fullmatch(agent_id):
        raise TopicSchemaError(
            f"agent_id '{agent_id}' is invalid; allowed: [a-z0-9_]+"
        )
    return agent_id


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
    Root: lucid/agents/<agent_id>
    """

    agent_username: str  # agent_id

    def __post_init__(self) -> None:
        _validate_agent_id(self.agent_username)

    @property
    def base(self) -> str:
        return f"lucid/agents/{self.agent_username}"

    # -------------------------
    # Agent retained
    # -------------------------
    def metadata(self) -> str:
        return f"{self.base}/metadata"

    def status(self) -> str:
        return f"{self.base}/status"

    def state(self) -> str:
        return f"{self.base}/state"

    def cfg(self) -> str:
        return f"{self.base}/cfg"

    def cfg_telemetry(self) -> str:
        return f"{self.base}/cfg/telemetry"

    # -------------------------
    # Agent stream
    # -------------------------
    def logs(self) -> str:
        return f"{self.base}/logs"

    def telemetry(self, metric: str) -> str:
        return f"{self.base}/telemetry/{metric}"

    # -------------------------
    # Agent commands
    # -------------------------
    def cmd_ping(self) -> str:
        return f"{self.base}/cmd/ping"

    def cmd_restart(self) -> str:
        return f"{self.base}/cmd/restart"

    def cmd_reset(self) -> str:
        return f"{self.base}/cmd/reset"

    def cmd_components_install(self) -> str:
        return f"{self.base}/cmd/components/install"

    def cmd_components_uninstall(self) -> str:
        return f"{self.base}/cmd/components/uninstall"

    def cmd_components_enable(self) -> str:
        return f"{self.base}/cmd/components/enable"

    def cmd_components_disable(self) -> str:
        return f"{self.base}/cmd/components/disable"

    # -------------------------
    # Agent results
    # -------------------------
    def evt_result(self, action: str) -> str:
        return f"{self.base}/evt/{action}/result"

    def evt_components_result(self, action: str) -> str:
        return f"{self.base}/evt/components/{action}/result"

    # -------------------------
    # Component topics
    # -------------------------
    def component_base(self, component_id: str) -> str:
        _validate_component_id(component_id)
        return f"{self.base}/components/{component_id}"

    def component_cmd_reset(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/cmd/reset"

    def component_cmd_identify(self, component_id: str) -> str:
        return f"{self.component_base(component_id)}/cmd/identify"
