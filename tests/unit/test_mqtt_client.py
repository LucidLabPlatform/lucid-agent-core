"""
Unit tests for MQTT client
"""
import pytest
import json
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime


@pytest.mark.unit
class TestAgentMQTTClient:
    """Test MQTT client functionality"""
    
    @pytest.fixture
    def mqtt_client(self, mock_env):
        """Create MQTT client instance"""
        from mqtt_client import AgentMQTTClient
        return AgentMQTTClient(
            device_id='test-device-123',
            host='test.mqtt.local',
            port=1883,
            username='test-agent',
            password='test-password',
            version='1.0.0'
        )
    
    def test_init(self, mqtt_client):
        """Test client initialization"""
        assert mqtt_client.device_id == 'test-device-123'
        assert mqtt_client.host == 'test.mqtt.local'
        assert mqtt_client.port == 1883
        assert mqtt_client.username == 'test-agent'
        assert mqtt_client.password == 'test-password'
        assert mqtt_client.version == '1.0.0'
        assert mqtt_client.client_id == 'lucid.agent.test-agent'
        assert mqtt_client.status_topic == 'lucid/agents/test-agent/status'
    
    def test_create_status_payload_online(self, mqtt_client):
        """Test online status payload creation"""
        payload = mqtt_client._create_status_payload('online')
        data = json.loads(payload)
        
        assert data['state'] == 'online'
        assert data['version'] == '1.0.0'
        assert 'ts' in data
        # Check timestamp format (ISO format)
        datetime.fromisoformat(data['ts'].replace('Z', '+00:00'))
    
    def test_create_status_payload_offline(self, mqtt_client):
        """Test offline status payload creation"""
        payload = mqtt_client._create_status_payload('offline')
        data = json.loads(payload)
        
        assert data['state'] == 'offline'
        assert 'ts' in data
    
    @patch('mqtt_client.mqtt.Client')
    def test_connect_success(self, mock_mqtt_class, mqtt_client):
        """Test successful connection"""
        mock_client_instance = MagicMock()
        mock_mqtt_class.return_value = mock_client_instance
        mock_client_instance.connect.return_value = None
        
        result = mqtt_client.connect()
        
        assert result is True
        mock_client_instance.username_pw_set.assert_called_once_with('test-agent', 'test-password')
        mock_client_instance.will_set.assert_called_once()
        mock_client_instance.connect.assert_called_once_with('test.mqtt.local', 1883, keepalive=60)
        mock_client_instance.loop_start.assert_called_once()
    
    @patch('mqtt_client.mqtt.Client')
    def test_connect_failure(self, mock_mqtt_class, mqtt_client):
        """Test connection failure"""
        mock_client_instance = MagicMock()
        mock_mqtt_class.return_value = mock_client_instance
        mock_client_instance.connect.side_effect = Exception("Connection refused")
        
        result = mqtt_client.connect()
        
        assert result is False
    
    @patch('mqtt_client.mqtt.Client')
    def test_disconnect(self, mock_mqtt_class, mqtt_client):
        """Test disconnection"""
        mock_client_instance = MagicMock()
        mock_mqtt_class.return_value = mock_client_instance
        mqtt_client.connect()
        
        mqtt_client.disconnect()
        
        # Should publish offline status
        assert mock_client_instance.publish.called
        # Should stop loop and disconnect
        mock_client_instance.loop_stop.assert_called_once()
        mock_client_instance.disconnect.assert_called_once()
    
    def test_is_connected(self, mqtt_client):
        """Test connection status check"""
        # Not connected initially
        assert mqtt_client.is_connected() is False
        
        # Mock connected client
        mqtt_client.client = MagicMock()
        mqtt_client.client.is_connected.return_value = True
        assert mqtt_client.is_connected() is True
        
        mqtt_client.client.is_connected.return_value = False
        assert mqtt_client.is_connected() is False
    
    def test_publish_dict(self, mqtt_client):
        """Test publishing dict payload"""
        mqtt_client.client = MagicMock()
        
        payload = {'test': 'data', 'value': 123}
        mqtt_client.publish('test/topic', payload, qos=1, retain=True)
        
        # Should serialize dict to JSON
        mqtt_client.client.publish.assert_called_once()
        call_args = mqtt_client.client.publish.call_args
        assert call_args[0][0] == 'test/topic'
        assert json.loads(call_args[0][1]) == payload
        assert call_args[1]['qos'] == 1
        assert call_args[1]['retain'] is True
    
    def test_publish_string(self, mqtt_client):
        """Test publishing string payload"""
        mqtt_client.client = MagicMock()
        
        payload = "test message"
        mqtt_client.publish('test/topic', payload)
        
        mqtt_client.client.publish.assert_called_once_with(
            'test/topic', 
            payload, 
            qos=0, 
            retain=False
        )
    
    def test_on_connect_callback(self, mqtt_client):
        """Test on_connect callback"""
        mock_client = MagicMock()
        mqtt_client.client = mock_client
        
        mqtt_client._on_connect(mock_client, None, None, 0)
        
        # Should publish online status
        assert mock_client.publish.called
    
    def test_on_disconnect_callback(self, mqtt_client):
        """Test on_disconnect callback"""
        # Unexpected disconnect
        mqtt_client._on_disconnect(None, None, 1)
        
        # Clean disconnect
        mqtt_client._on_disconnect(None, None, 0)
    
    def test_topic_schema_integration(self, mqtt_client):
        """Test that TopicSchema is properly integrated"""
        assert mqtt_client.topics is not None
        assert mqtt_client.topics.agent_username == 'test-agent'
        assert mqtt_client.status_topic == mqtt_client.topics.status()
