"""
Minimal dummy component for testing load/start/stop.

Entrypoint: lucid_agent_core.components.dummy:DummyComponent
"""
from __future__ import annotations

from lucid_component_base import Component
from lucid_component_base.context import ComponentContext


class DummyComponent(Component):
    """No-op component for regression tests."""

    @property
    def component_id(self) -> str:
        return "dummy"

    def _start(self) -> None:
        pass

    def _stop(self) -> None:
        pass
