"""
Integration tests for main agent
"""
import pytest
import sys
import signal
from unittest.mock import Mock, MagicMock, patch


@pytest.mark.integration
class TestMainAgent:
    """Test main agent lifecycle"""
    
    @patch('main.AgentMQTTClient')
    def test_main_successful_startup(self, mock_mqtt_class, mock_env):
        """Test successful agent startup"""
        # Mock MQTT client
        mock_mqtt_instance = MagicMock()
        mock_mqtt_instance.connect.return_value = True
        mock_mqtt_instance.is_connected.return_value = True
        mock_mqtt_class.return_value = mock_mqtt_instance
        
        # Import and run main (will be interrupted by our timeout)
        import main
        
        # Test with early exit via KeyboardInterrupt
        with patch('main.time.sleep') as mock_sleep:
            mock_sleep.side_effect = KeyboardInterrupt
            
            main.main()
            
            # Verify initialization sequence
            assert mock_mqtt_class.called
            mock_mqtt_instance.connect.assert_called_once()
            
            # Verify cleanup on interrupt
            mock_mqtt_instance.disconnect.assert_called_once()
    
    @patch('main.AgentMQTTClient')
    def test_main_connection_failure(self, mock_mqtt_class, mock_env):
        """Test agent fails to connect"""
        mock_mqtt_instance = MagicMock()
        mock_mqtt_instance.connect.return_value = False
        mock_mqtt_class.return_value = mock_mqtt_instance
        
        import main
        
        with pytest.raises(SystemExit) as exc_info:
            main.main()
        
        assert exc_info.value.code == 1
    
    @patch('main.AgentMQTTClient')
    def test_main_connection_lost(self, mock_mqtt_class, mock_env):
        """Test agent connects but loses connection"""
        mock_mqtt_instance = MagicMock()
        mock_mqtt_instance.connect.return_value = True
        mock_mqtt_instance.is_connected.return_value = False
        mock_mqtt_class.return_value = mock_mqtt_instance
        
        import main
        
        with patch('main.time.sleep'):
            with pytest.raises(SystemExit) as exc_info:
                main.main()
            
            assert exc_info.value.code == 1
    
    @patch('main.AgentMQTTClient')
    def test_signal_handler_sigint(self, mock_mqtt_class, mock_env):
        """Test SIGINT signal handling"""
        mock_mqtt_instance = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt_instance
        
        import main
        
        # Set global
        main.agent = mock_mqtt_instance
        
        # Call signal handler
        with pytest.raises(SystemExit):
            main.signal_handler(signal.SIGINT, None)
        
        # Should shutdown gracefully
        mock_mqtt_instance.disconnect.assert_called_once()
    
    @patch('main.AgentMQTTClient')
    def test_signal_handler_sigterm(self, mock_mqtt_class, mock_env):
        """Test SIGTERM signal handling"""
        mock_mqtt_instance = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt_instance
        
        import main
        
        # Set global
        main.agent = mock_mqtt_instance
        
        # Call signal handler
        with pytest.raises(SystemExit):
            main.signal_handler(signal.SIGTERM, None)
        
        # Should shutdown gracefully
        mock_mqtt_instance.disconnect.assert_called_once()


@pytest.mark.unit
class TestMainHelpers:
    """Test helper functions"""
    
    def test_imports(self, mock_env):
        """Test all imports work"""
        import main
        from main import AgentMQTTClient
        from main import DEVICE_ID, MQTT_HOST, MQTT_PORT, AGENT_USERNAME, AGENT_PASSWORD, AGENT_VERSION
        
        assert MQTT_HOST == 'test.mqtt.local'
        assert MQTT_PORT == 1883
        assert AGENT_USERNAME == 'test-agent'

