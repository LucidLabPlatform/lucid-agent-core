# lucid_agent_core/components/base.py

from __future__ import annotations
from abc import ABC, abstractmethod


class Component(ABC):
    """
    Base class for all LUCID components.

    Components are instantiated and managed by agent-core.
    They must not create their own MQTT clients or manage system state.
    """

    component_id: str

    def __init__(self, context):
        self.context = context

    @abstractmethod
    def start(self) -> None:
        """Start the component. Subscribe to MQTT and initialize hardware here."""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """Stop the component. Release resources and unsubscribe."""
        raise NotImplementedError
