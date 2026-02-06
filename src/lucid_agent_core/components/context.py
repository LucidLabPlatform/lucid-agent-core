# lucid_agent_core/components/context.py

from __future__ import annotations
import logging


class ComponentContext:
    """
    Shared runtime context passed to all components.
    """

    def __init__(self, agent_id, mqtt_client, config):
        self.agent_id = agent_id
        self.mqtt = mqtt_client
        self.config = config
        self.logger = logging.getLogger("lucid.component")
