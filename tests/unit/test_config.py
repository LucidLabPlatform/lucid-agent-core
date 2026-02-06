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

    def test_missing_required_env_var(self, monkeypatch):
        """Test that missing required variables cause exit"""
        for key in ["MQTT_HOST", "MQTT_PORT", "AGENT_USERNAME", "AGENT_PASSWORD"]:
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
