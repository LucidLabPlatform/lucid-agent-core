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
        'COMPONENT_REGISTRY': 'ghcr.io/test/lucid'
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


@pytest.fixture
def mock_docker():
    """Mock Docker commands"""
    mock = MagicMock()
    mock.run.return_value = MagicMock(
        returncode=0,
        stdout="container_id_12345",
        stderr=""
    )
    return mock


@pytest.fixture
def sample_component_config():
    """Sample component configuration"""
    return {
        'component_type': 'led',
        'component_id': 'test_led',
        'version': '1.0.0',
        'config': {
            'gpio_pin': 18,
            'simulated': True
        }
    }


@pytest.fixture
def sample_capabilities():
    """Sample component capabilities"""
    return [
        {
            'action': 'power_on',
            'description': 'Turn LED on'
        },
        {
            'action': 'power_off',
            'description': 'Turn LED off'
        },
        {
            'action': 'set_brightness',
            'description': 'Set LED brightness',
            'parameters': {
                'brightness': {
                    'type': 'integer',
                    'min': 0,
                    'max': 100
                }
            }
        }
    ]
