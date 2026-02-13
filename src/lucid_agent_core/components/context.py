"""
Component context — shared runtime passed to all components.

Provides agent_id, MQTT publisher, config, and topic schema.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from lucid_agent_core.mqtt_topics import TopicSchema


class MqttPublisher(Protocol):
    """
    Minimal interface components need from the MQTT client.
    Keep it small to prevent tight coupling.
    """

    def publish(self, topic: str, payload, *, qos: int = 0, retain: bool = False) -> None: ...


@dataclass(frozen=True, slots=True)
class ComponentContext:
    """
    Shared runtime context passed to all components.

    Rules:
    - agent_id must be stable and non-empty.
    - mqtt must expose the publish() API.
    - topics is the single source of truth for all topic construction.
    """

    agent_id: str
    mqtt: MqttPublisher
    config: object
    topics: TopicSchema

    def logger(self, component_id: str) -> logging.Logger:
        """
        Component-scoped logger name.
        """
        return logging.getLogger(f"lucid.component.{component_id}")

    @staticmethod
    def create(*, agent_id: str, mqtt: MqttPublisher, config: object) -> "ComponentContext":
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("agent_id must be a non-empty string")
        return ComponentContext(agent_id=agent_id, mqtt=mqtt, config=config, topics=TopicSchema(agent_id))
