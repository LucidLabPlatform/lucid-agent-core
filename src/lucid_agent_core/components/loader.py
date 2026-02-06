# lucid_agent_core/components/loader.py

from __future__ import annotations
import importlib
import logging

from lucid_agent_core.components.base import Component
from lucid_agent_core.components.context import ComponentContext
from lucid_agent_core.components.registry import load_registry

logger = logging.getLogger(__name__)


def load_components(context: ComponentContext) -> list[Component]:
    """
    Load and start all registered components.

    Component failures are isolated and must not crash the agent.
    """
    components = []
    registry = load_registry()

    for component_id, meta in registry.items():
        entrypoint = meta.get("entrypoint")
        if not entrypoint:
            logger.error("Component %s missing entrypoint", component_id)
            continue

        try:
            module_path, class_name = entrypoint.split(":")
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)

            component = cls(context)

            if not isinstance(component, Component):
                raise TypeError("Not a Component subclass")

            component.start()
            components.append(component)

            logger.info("Component loaded: %s", component_id)

        except Exception as e:
            logger.exception("Failed to load component %s: %s", component_id, e)

    return components
