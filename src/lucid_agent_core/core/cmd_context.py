"""
Core command context for LUCID Agent Core.

Provides command handlers with MQTT publishing capabilities, topic schema,
agent metadata, and configuration store access.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from lucid_agent_core.mqtt_topics import TopicSchema

logger = logging.getLogger(__name__)


class MqttPublisher(Protocol):
    """
    Minimal MQTT publisher interface for command context.

    This protocol defines the contract that the MQTT client must fulfill.
    """

    def publish(
        self, topic: str, payload: Any, *, qos: int = 0, retain: bool = False
    ) -> Any:
        """Publish a message to MQTT broker."""
        ...


class ConfigStore(Protocol):
    """Protocol for configuration store interface."""

    def get_cached(self) -> dict[str, Any]:
        """Return cached configuration."""
        ...

    def apply_set(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Apply configuration changes."""
        ...


def _utc_iso() -> str:
    """Return current UTC timestamp as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CoreCommandContext:
    """
    Command execution context for core handlers.

    Provides:
    - MQTT publishing with JSON encoding
    - Topic schema for consistent topic construction
    - Agent identity and version
    - Configuration store access
    - Helper methods for event publishing
    """

    mqtt: MqttPublisher
    topics: TopicSchema
    agent_id: str
    agent_version: str
    config_store: ConfigStore

    def publish(
        self, topic: str, payload: dict[str, Any], *, retain: bool = False, qos: int = 1
    ) -> Any:
        """
        Publish a dict payload to MQTT with JSON encoding.

        Args:
            topic: MQTT topic to publish to
            payload: Dict to JSON-encode and publish
            retain: Whether to retain the message
            qos: Quality of service level (default 1 for commands/events)

        Returns:
            MQTTMessageInfo object for wait_for_publish()

        Raises:
            Exception: If JSON encoding or publish fails
        """
        try:
            payload_str = json.dumps(payload)
        except (TypeError, ValueError) as exc:
            logger.error("Failed to JSON-encode payload for %s: %s", topic, exc)
            raise

        return self.mqtt.publish(topic, payload_str, qos=qos, retain=retain)

    def publish_error(
        self,
        evt_topic: str,
        request_id: str,
        error: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Publish a standardized error event.

        Args:
            evt_topic: Event topic to publish to
            request_id: Request ID from original command
            error: Error message
            details: Optional additional error details
        """
        payload: dict[str, Any] = {
            "request_id": request_id,
            "ok": False,
            "error": error,
            "ts": _utc_iso(),
        }

        if details:
            payload.update(details)

        try:
            self.publish(evt_topic, payload, retain=False, qos=1)
            logger.info("Published error event to %s: %s", evt_topic, error)
        except Exception as exc:
            logger.exception("Failed to publish error event to %s: %s", evt_topic, exc)

    @staticmethod
    def now_ts() -> str:
        """Return current UTC timestamp as ISO8601 string."""
        return _utc_iso()
