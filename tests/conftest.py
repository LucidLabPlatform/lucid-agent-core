"""
Pytest configuration and shared fixtures
"""
import os
import sys
import pytest
from unittest.mock import Mock, MagicMock

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture
def mock_env(monkeypatch):
    """Set up mock environment variables"""
    env_vars = {
        'MQTT_HOST': 'test.mqtt.local',
        'MQTT_PORT': '1883',
        'AGENT_USERNAME': 'test-agent',
        'AGENT_PASSWORD': 'test-password',
        'AGENT_VERSION': '1.0.0-test',
        'AGENT_HEARTBEAT': '30'
    }
    
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    
    return env_vars


@pytest.fixture
def mock_mqtt_client():
    """Create a mock MQTT client"""
    client = MagicMock()
    client.is_connected.return_value = True
    client.publish.return_value = (0, 1)  # (rc, mid)
    return client


