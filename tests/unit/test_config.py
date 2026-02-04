"""
Unit tests for configuration module
"""
import pytest
import sys
from unittest.mock import patch


@pytest.mark.unit
class TestConfig:
    """Test configuration loading"""

    def test_all_required_env_vars_present(self, mock_env):
        """Test config loads when all required variables are present"""
        import lucid_agent_core.config as config
        config.load_config()
        assert config.MQTT_HOST == "test.mqtt.local"
        assert config.MQTT_PORT == 1883
        assert config.AGENT_USERNAME == "test-agent"
        assert config.AGENT_PASSWORD == "test-password"
        assert config.AGENT_VERSION == "1.0.0-test"
        assert config.DEVICE_ID is not None
        assert len(config.DEVICE_ID) == 36  # UUID format

    def test_missing_required_env_var(self, monkeypatch):
        """Test that missing required variables cause exit"""
        for key in ["MQTT_HOST", "MQTT_PORT", "AGENT_USERNAME", "AGENT_PASSWORD", "AGENT_VERSION"]:
            monkeypatch.delenv(key, raising=False)

        import lucid_agent_core.config as config
        with patch("dotenv.load_dotenv"):
            with pytest.raises(SystemExit) as exc_info:
                config.load_config()
        assert exc_info.value.code == 1

    def test_port_is_integer(self, mock_env):
        """Test MQTT_PORT is converted to integer"""
        import lucid_agent_core.config as config
        config.load_config()
        assert isinstance(config.MQTT_PORT, int)
        assert config.MQTT_PORT == 1883

    def test_device_id_is_unique(self, mock_env):
        """Test that DEVICE_ID generates valid UUIDs"""
        import lucid_agent_core.config as config
        config.load_config()
        device_id_1 = config.DEVICE_ID
        config.load_config()
        device_id_2 = config.DEVICE_ID
        assert isinstance(device_id_1, str)
        assert isinstance(device_id_2, str)
        assert len(device_id_1) == 36
        assert len(device_id_2) == 36
