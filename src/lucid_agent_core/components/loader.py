from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any

from lucid_component_base import Component, ComponentContext
from lucid_agent_core.components.registry import load_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ComponentLoadResult:
    component_id: str
    ok: bool
    entrypoint: str | None = None
    error: str | None = None
    started: bool = False


def _parse_entrypoint(entrypoint: str) -> tuple[str, str]:
    if ":" not in entrypoint:
        raise ValueError("entrypoint must be in format 'module.path:ClassName'")
    module_path, class_name = entrypoint.split(":", 1)
    if not module_path or not class_name:
        raise ValueError("entrypoint must include both module and class")
    return module_path, class_name


def load_components(
    agent_id: str,
    base_topic: str,
    mqtt: Any,
    config: object,
    *,
    registry: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[Component], list[ComponentLoadResult]]:
    """
    Load components from the registry.

    Policy (v1.0.0):
    - enabled: default True (skip if False)
    - auto_start: default True (start immediately if True)

    This does not implement MQTT-driven start/stop yet; it is boot-time behavior only.
    """
    components: list[Component] = []
    results: list[ComponentLoadResult] = []

    reg = registry if registry is not None else load_registry()

    for component_id, meta in reg.items():
        context = ComponentContext.create(
            agent_id=agent_id,
            base_topic=base_topic,
            component_id=component_id,
            mqtt=mqtt,
            config=config,
        )
        clog = context.logger()

        entrypoint = meta.get("entrypoint")
        if not isinstance(entrypoint, str) or not entrypoint:
            msg = "missing/invalid entrypoint"
            clog.error(msg)
            results.append(ComponentLoadResult(component_id=component_id, ok=False, error=msg))
            continue

        enabled = meta.get("enabled", True)
        # Always load components, but only start them if enabled
        auto_start = meta.get("auto_start", True) and enabled

        try:
            module_path, class_name = _parse_entrypoint(entrypoint)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)

            if not isinstance(cls, type) or not issubclass(cls, Component):
                raise TypeError(f"entrypoint class is not a Component subclass: {entrypoint}")

            component: Component = cls(context)

            # Ensure component_id contract is consistent
            if component.component_id != component_id:
                clog.warning(
                    "component_id mismatch: registry=%s class=%s; using registry id as source of truth",
                    component_id,
                    component.component_id,
                )

            started = False
            if auto_start:
                component.start()
                started = True

            components.append(component)
            results.append(
                ComponentLoadResult(
                    component_id=component_id,
                    ok=True,
                    entrypoint=entrypoint,
                    started=started,
                )
            )
            if enabled is False:
                clog.info("loaded but disabled (not started)")
            else:
                clog.info("loaded (auto_start=%s)", auto_start)

        except Exception as exc:
            clog.exception("failed to load (entrypoint=%s)", entrypoint)
            results.append(
                ComponentLoadResult(
                    component_id=component_id,
                    ok=False,
                    entrypoint=entrypoint,
                    error=str(exc),
                    started=False,
                )
            )

    return components, results
