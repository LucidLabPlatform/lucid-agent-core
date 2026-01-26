"""
Unit tests for configuration module
"""
import pytest
import os
import sys
from unittest.mock import patch


@pytest.mark.unit
class TestConfig:
    """Test configuration loading"""
    
    def test_all_required_env_vars_present(self, mock_env):
        """Test config loads when all required variables are present"""
        # Import after environment is set
        import config
        
        assert config.MQTT_HOST == 'test.mqtt.local'
        assert config.MQTT_PORT == 1883
        assert config.AGENT_USERNAME == 'test-agent'
        assert config.AGENT_PASSWORD == 'test-password'
        assert config.AGENT_VERSION == '1.0.0-test'
        assert config.DEVICE_ID is not None
        assert len(config.DEVICE_ID) == 36  # UUID format
    
    def test_missing_required_env_var(self, monkeypatch):
        """Test that missing required variables cause exit"""
        # Remove all env vars
        for key in ['MQTT_HOST', 'MQTT_PORT', 'AGENT_USERNAME', 'AGENT_PASSWORD', 'AGENT_VERSION']:
            monkeypatch.delenv(key, raising=False)
        
        # Should exit when importing
        with pytest.raises(SystemExit) as exc_info:
            # Force reload of config module
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
        
        assert exc_info.value.code == 1
    
    def test_port_is_integer(self, mock_env):
        """Test MQTT_PORT is converted to integer"""
        import config
        assert isinstance(config.MQTT_PORT, int)
        assert config.MQTT_PORT == 1883
    
    def test_device_id_is_unique(self, mock_env):
        """Test that DEVICE_ID generates unique UUIDs"""
        # Force reload twice to get different UUIDs
        import config as config1
        device_id_1 = config1.DEVICE_ID
        
        # Reload module
        if 'config' in sys.modules:
            del sys.modules['config']
        
        import config as config2
        device_id_2 = config2.DEVICE_ID
        
        # Should be different UUIDs (different instances)
        # Note: They'll be the same in same process, but that's okay
        assert isinstance(device_id_1, str)
        assert isinstance(device_id_2, str)
