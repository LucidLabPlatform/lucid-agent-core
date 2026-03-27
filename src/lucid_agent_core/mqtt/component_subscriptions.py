"""
Component subscription helpers — subscribe/unsubscribe MQTT cmd topics for components.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def action_to_method_name(action: str) -> str:
    """Convert a command action path (e.g. 'effect/color-wipe') to a handler method name."""
    return "on_cmd_" + action.replace("/", "_").replace("-", "_")


def subscribe_component_topics(
    paho_client: Any,
    handlers: dict[str, Any],
    component_cmd_topics: dict[str, set[str]],
    topics: Any,
    comp: Any,
    component_id: str,
) -> None:
    """
    Subscribe to all cmd topics for a single component, registering handlers.

    Modifies *handlers* and *component_cmd_topics* in place.
    """
    if not paho_client or not paho_client.is_connected():
        return

    caps = getattr(comp, "capabilities", None)
    cap_list = list(caps()) if callable(caps) else []
    topics_for_cid = component_cmd_topics.setdefault(component_id, set())

    for action in cap_list:
        method_name = action_to_method_name(action)
        method = getattr(comp, method_name, None)
        if not callable(method):
            continue
        try:
            topic = topics.component_cmd(component_id, action)
        except Exception:
            continue
        if topic in handlers:
            continue
        handlers[topic] = comp._make_cmd_handler(action, method)
        paho_client.subscribe(topic, qos=1)
        topics_for_cid.add(topic)
        logger.info("Subscribed: %s", topic)
        logger.debug("Registered handler: topic=%s handler=%s", topic, method.__name__)

    for cfg_action, attr_name in (
        ("cfg/set", "on_cmd_cfg_set"),
        ("cfg/logging/set", "on_cmd_cfg_logging_set"),
        ("cfg/telemetry/set", "on_cmd_cfg_telemetry_set"),
    ):
        method = getattr(comp, attr_name, None)
        if not callable(method):
            continue
        if cfg_action == "cfg/set":
            topic = topics.component_cmd_cfg_set(component_id)
        elif cfg_action == "cfg/logging/set":
            topic = topics.component_cmd_cfg_logging_set(component_id)
        else:
            topic = topics.component_cmd_cfg_telemetry_set(component_id)
        if topic not in handlers:
            handlers[topic] = comp._make_cmd_handler(cfg_action, method)
            paho_client.subscribe(topic, qos=1)
            topics_for_cid.add(topic)
            logger.info("Subscribed: %s", topic)


def add_component_handlers(
    paho_client: Any,
    handlers: dict[str, Any],
    component_cmd_topics: dict[str, set[str]],
    topics: Any,
    components: list[Any],
    registry: dict[str, dict],
) -> None:
    """
    Subscribe to cmd topics for a list of components, gated by enabled status in registry.

    Modifies *handlers* and *component_cmd_topics* in place.
    """
    if not paho_client or not paho_client.is_connected():
        logger.warning("add_component_handlers called but client not connected")
        return

    for comp in components:
        cid = getattr(comp, "component_id", None)
        if not cid:
            continue
        if cid in registry and registry[cid].get("enabled") is False:
            logger.info("Skipping cmd subscriptions for disabled component: %s", cid)
            continue
        subscribe_component_topics(paho_client, handlers, component_cmd_topics, topics, comp, cid)


def unsubscribe_component_topics(
    paho_client: Any,
    handlers: dict[str, Any],
    topics_to_remove: set[str],
) -> None:
    """
    Unsubscribe from a set of component cmd topics, removing their handlers.

    Modifies *handlers* in place.
    """
    if not paho_client or not paho_client.is_connected():
        return
    for topic in topics_to_remove:
        if topic in handlers:
            try:
                paho_client.unsubscribe(topic)
                del handlers[topic]
                logger.info("Unsubscribed: %s", topic)
            except Exception as exc:
                logger.warning("Failed to unsubscribe %s: %s", topic, exc)
