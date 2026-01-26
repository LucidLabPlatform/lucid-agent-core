"""
Unit tests for MQTT topic schema
"""
import pytest
from mqtt_topics import TopicSchema


@pytest.mark.unit
class TestTopicSchema:
    """Test topic schema functionality"""
    
    @pytest.fixture
    def schema(self):
        """Create topic schema instance"""
        return TopicSchema('test-agent')
    
    def test_init(self, schema):
        """Test schema initialization"""
        assert schema.agent_username == 'test-agent'
        assert schema.base == 'lucid/agents/test-agent'
    
    def test_status_topic(self, schema):
        """Test status topic construction"""
        topic = schema.status()
        assert topic == 'lucid/agents/test-agent/status'
