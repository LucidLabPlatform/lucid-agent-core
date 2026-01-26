"""
MQTT Topic Schema for LUCID Agent
Minimal topic definitions for agent-only
"""

import logging

logger = logging.getLogger(__name__)


class TopicSchema:
    """MQTT topic schema for agent"""
    
    def __init__(self, agent_username: str):
        """
        Initialize topic schema for an agent
        
        Args:
            agent_username: Agent's unique username
        """
        self.agent_username = agent_username
        self.base = f"lucid/agents/{self.agent_username}"
    
    def status(self) -> str:
        """Agent status topic (retained)"""
        return f"{self.base}/status"
