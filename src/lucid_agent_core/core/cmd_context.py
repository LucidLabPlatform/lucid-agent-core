"""
Core command context for LUCID Agent Core — unified v1.0.0 contract.

Provides MQTT publishing, topic schema, and result payload shape: request_id, ok, error.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from lucid_agent_core.mqtt_topics import TopicSchema

logger = logging.getLogger(__name__)


class MqttPublisher(Protocol):
    """Minimal MQTT publisher interface for command context."""

    def publish(
        self, topic: str, payload: Any, *, qos: int = 0, retain: bool = False
    ) -> Any: ...


class ConfigStore(Protocol):
    """Protocol for configuration store interface."""

    def get_cached(self) -> dict[str, Any]:
        """Return cached configuration."""
        ...

    def apply_set(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Apply configuration changes."""
        ...


@dataclass
class CoreCommandContext:
    """
    Command execution context for core handlers.
    Result payload contract: { request_id, ok, error }.
    """

    mqtt: MqttPublisher
    topics: TopicSchema
    agent_id: str
    agent_version: str
    config_store: ConfigStore

    def publish(
        self, topic: str, payload: dict[str, Any], *, retain: bool = False, qos: int = 1
    ) -> Any:
        """Publish a dict payload to MQTT with JSON encoding."""
        try:
            payload_str = json.dumps(payload)
        except (TypeError, ValueError) as exc:
            logger.error("Failed to JSON-encode payload for %s: %s", topic, exc)
            raise
        return self.mqtt.publish(topic, payload_str, qos=qos, retain=retain)

    def publish_result(
        self,
        action: str,
        request_id: str,
        ok: bool,
        error: Optional[str] = None,
    ) -> None:
        """Publish evt/<action>/result. Contract: request_id, ok, error."""
        topic = self.topics.evt_result(action)
        payload = {"request_id": request_id, "ok": ok, "error": error}
        try:
            self.publish(topic, payload, retain=False, qos=1)
        except Exception as exc:
            logger.exception("Failed to publish result to %s: %s", topic, exc)

    def publish_result_error(
        self,
        topic: str,
        request_id: str,
        error: str,
    ) -> None:
        """Publish result with ok=False to any result topic."""
        payload = {"request_id": request_id, "ok": False, "error": error}
        try:
            self.publish(topic, payload, retain=False, qos=1)
        except Exception as exc:
            logger.exception("Failed to publish error result to %s: %s", topic, exc)
