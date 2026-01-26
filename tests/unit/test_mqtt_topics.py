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
    
    def test_capabilities_topic(self, schema):
        """Test capabilities topic construction"""
        topic = schema.capabilities()
        assert topic == 'lucid/agents/test-agent/components/list'
    
    def test_cmd_component_lifecycle(self, schema):
        """Test lifecycle command topic construction"""
        # Valid actions
        assert schema.cmd_component_lifecycle('install') == \
            'lucid/agents/test-agent/cmd/components/install'
        assert schema.cmd_component_lifecycle('uninstall') == \
            'lucid/agents/test-agent/cmd/components/uninstall'
        assert schema.cmd_component_lifecycle('start') == \
            'lucid/agents/test-agent/cmd/components/start'
        assert schema.cmd_component_lifecycle('stop') == \
            'lucid/agents/test-agent/cmd/components/stop'
        assert schema.cmd_component_lifecycle('list') == \
            'lucid/agents/test-agent/cmd/components/list'
    
    def test_cmd_component_lifecycle_invalid_action(self, schema):
        """Test lifecycle command with invalid action"""
        with pytest.raises(ValueError, match="Invalid lifecycle action"):
            schema.cmd_component_lifecycle('invalid_action')
    
    def test_cmd_component_action(self, schema):
        """Test component action topic construction"""
        topic = schema.cmd_component_action('test_led', 'power_on')
        assert topic == 'lucid/agents/test-agent/cmd/test_led/power_on'
    
    def test_evt_component_lifecycle(self, schema):
        """Test lifecycle event response topic"""
        topic = schema.evt_component_lifecycle('install')
        assert topic == 'lucid/agents/test-agent/evt/components/install/response'
    
    def test_evt_component_event(self, schema):
        """Test component event topic"""
        topic = schema.evt_component_event('test_led', 'power_on_complete')
        assert topic == 'lucid/agents/test-agent/evt/test_led/power_on_complete'
    
    def test_component_register(self, schema):
        """Test component registration topic"""
        topic = schema.component_register('test_led')
        assert topic == 'lucid/agents/test-agent/components/test_led/register'
    
    # Component ID validation tests
    
    def test_component_id_validation_valid(self, schema):
        """Test valid component IDs"""
        # These should not raise
        schema.cmd_component_action('valid_id', 'action')
        schema.cmd_component_action('valid-id', 'action')
        schema.cmd_component_action('ValidID123', 'action')
        schema.cmd_component_action('a', 'action')
        schema.cmd_component_action('LED_1', 'action')
    
    def test_component_id_validation_empty(self, schema):
        """Test empty component ID"""
        with pytest.raises(ValueError, match="Component ID cannot be empty"):
            schema.cmd_component_action('', 'action')
    
    def test_component_id_validation_with_slash(self, schema):
        """Test component ID with slash (MQTT wildcard)"""
        with pytest.raises(ValueError, match="contains MQTT wildcards or slashes"):
            schema.cmd_component_action('test/led', 'action')
    
    def test_component_id_validation_with_hash(self, schema):
        """Test component ID with hash (MQTT wildcard)"""
        with pytest.raises(ValueError, match="contains MQTT wildcards or slashes"):
            schema.cmd_component_action('test#led', 'action')
    
    def test_component_id_validation_with_plus(self, schema):
        """Test component ID with plus (MQTT wildcard)"""
        with pytest.raises(ValueError, match="contains MQTT wildcards or slashes"):
            schema.cmd_component_action('test+led', 'action')
    
    def test_component_id_validation_with_spaces(self, schema):
        """Test component ID with spaces"""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            schema.cmd_component_action('test led', 'action')
    
    def test_component_id_validation_with_special_chars(self, schema):
        """Test component ID with special characters"""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            schema.cmd_component_action('test@led', 'action')
        
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            schema.cmd_component_action('test$led', 'action')
    
    # Topic parsing tests
    
    def test_parse_command_lifecycle_install(self, schema):
        """Test parsing install command"""
        topic = 'lucid/agents/test-agent/cmd/components/install'
        parsed = schema.parse_command(topic)
        
        assert parsed is not None
        assert parsed['type'] == 'lifecycle'
        assert parsed['action'] == 'install'
    
    def test_parse_command_lifecycle_uninstall(self, schema):
        """Test parsing uninstall command"""
        topic = 'lucid/agents/test-agent/cmd/components/uninstall'
        parsed = schema.parse_command(topic)
        
        assert parsed is not None
        assert parsed['type'] == 'lifecycle'
        assert parsed['action'] == 'uninstall'
    
    def test_parse_command_lifecycle_start(self, schema):
        """Test parsing start command"""
        topic = 'lucid/agents/test-agent/cmd/components/start'
        parsed = schema.parse_command(topic)
        
        assert parsed is not None
        assert parsed['type'] == 'lifecycle'
        assert parsed['action'] == 'start'
    
    def test_parse_command_lifecycle_stop(self, schema):
        """Test parsing stop command"""
        topic = 'lucid/agents/test-agent/cmd/components/stop'
        parsed = schema.parse_command(topic)
        
        assert parsed is not None
        assert parsed['type'] == 'lifecycle'
        assert parsed['action'] == 'stop'
    
    def test_parse_command_lifecycle_list(self, schema):
        """Test parsing list command"""
        topic = 'lucid/agents/test-agent/cmd/components/list'
        parsed = schema.parse_command(topic)
        
        assert parsed is not None
        assert parsed['type'] == 'lifecycle'
        assert parsed['action'] == 'list'
    
    def test_parse_command_component_action(self, schema):
        """Test parsing component action command"""
        topic = 'lucid/agents/test-agent/cmd/test_led/power_on'
        parsed = schema.parse_command(topic)
        
        assert parsed is not None
        assert parsed['type'] == 'action'
        assert parsed['component_id'] == 'test_led'
        assert parsed['action'] == 'power_on'
    
    def test_parse_command_component_action_with_hyphen(self, schema):
        """Test parsing component action with hyphenated component ID"""
        topic = 'lucid/agents/test-agent/cmd/ceiling-led/set_brightness'
        parsed = schema.parse_command(topic)
        
        assert parsed is not None
        assert parsed['type'] == 'action'
        assert parsed['component_id'] == 'ceiling-led'
        assert parsed['action'] == 'set_brightness'
    
    def test_parse_command_invalid_base(self, schema):
        """Test parsing command with wrong base"""
        topic = 'lucid/agents/other-agent/cmd/components/install'
        parsed = schema.parse_command(topic)
        
        assert parsed is None
    
    def test_parse_command_not_command(self, schema):
        """Test parsing non-command topic"""
        topic = 'lucid/agents/test-agent/status'
        parsed = schema.parse_command(topic)
        
        assert parsed is None
    
    def test_parse_command_invalid_component_id(self, schema):
        """Test parsing command with invalid component ID"""
        topic = 'lucid/agents/test-agent/cmd/test/led/power_on'
        parsed = schema.parse_command(topic)
        
        # Should return None because component_id contains slash
        assert parsed is None
    
    def test_parse_command_incomplete_topic(self, schema):
        """Test parsing incomplete command topic"""
        topic = 'lucid/agents/test-agent/cmd/components'
        parsed = schema.parse_command(topic)
        
        assert parsed is None
    
    def test_parse_command_incomplete_action_topic(self, schema):
        """Test parsing incomplete action command topic"""
        topic = 'lucid/agents/test-agent/cmd/test_led'
        parsed = schema.parse_command(topic)
        
        assert parsed is None
    
    def test_parse_command_empty_parts(self, schema):
        """Test parsing command with empty parts"""
        topic = 'lucid/agents/test-agent/cmd//install'
        parsed = schema.parse_command(topic)
        
        # Should fail validation for empty component_id
        assert parsed is None
