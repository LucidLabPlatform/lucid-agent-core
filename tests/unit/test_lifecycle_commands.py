"""
Tests for component lifecycle commands (install, uninstall, enable, disable).
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lucid_agent_core.core.handlers import (
    on_components_install,
    on_components_uninstall,
    on_components_enable,
    on_components_disable,
)
from lucid_agent_core.core.cmd_context import CoreCommandContext
from lucid_agent_core.mqtt_topics import TopicSchema


@pytest.fixture
def mock_ctx(tmp_path):
    """Create mock command context."""
    mqtt = MagicMock()
    topics = TopicSchema("test")
    config_store = MagicMock()
    config_store.get_cached.return_value = {}
    
    return CoreCommandContext(
        mqtt=mqtt,
        topics=topics,
        agent_id="test",
        agent_version="1.0.0",
        config_store=config_store,
    )


@pytest.fixture
def mock_registry(tmp_path):
    """Setup mock registry file."""
    registry_path = tmp_path / "components_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    
    registry = {
        "fixture_cpu": {
            "component_id": "fixture_cpu",
            "version": "1.0.0",
            "enabled": True,
            "entrypoint": "test:Test",
        }
    }
    registry_path.write_text(json.dumps(registry))
    
    return registry_path


def test_enable_command_updates_registry_and_state(mock_ctx, mock_registry, monkeypatch):
    """Test enable command sets enabled=true and republishes state."""
    monkeypatch.setenv("LUCID_AGENT_BASE_DIR", str(mock_registry.parent.parent))
    
    payload = json.dumps({"request_id": "req123", "component_id": "fixture_cpu"})
    
    with patch("lucid_agent_core.core.handlers.load_registry") as mock_load:
        with patch("lucid_agent_core.core.handlers.write_registry") as mock_write:
            mock_load.return_value = {
                "fixture_cpu": {
                    "component_id": "fixture_cpu",
                    "version": "1.0.0",
                    "enabled": False,
                }
            }
            
            on_components_enable(mock_ctx, payload)
            
            # Verify enabled set to True
            assert mock_write.called
            written_registry = mock_write.call_args[0][0]
            assert written_registry["fixture_cpu"]["enabled"] is True
            
            # Verify state was published
            state_publishes = [
                call for call in mock_ctx.mqtt.publish.call_args_list
                if "state" in str(call[0][0])
            ]
            assert len(state_publishes) > 0
            
            # Verify result published
            result_publishes = [
                call for call in mock_ctx.mqtt.publish.call_args_list
                if "evt/components/enable/result" in str(call[0][0])
            ]
            assert len(result_publishes) == 1


def test_disable_command_updates_registry_and_state(mock_ctx, mock_registry, monkeypatch):
    """Test disable command sets enabled=false and republishes state."""
    monkeypatch.setenv("LUCID_AGENT_BASE_DIR", str(mock_registry.parent.parent))
    
    payload = json.dumps({"request_id": "req123", "component_id": "fixture_cpu"})
    
    with patch("lucid_agent_core.core.handlers.load_registry") as mock_load:
        with patch("lucid_agent_core.core.handlers.write_registry") as mock_write:
            mock_load.return_value = {
                "fixture_cpu": {
                    "component_id": "fixture_cpu",
                    "version": "1.0.0",
                    "enabled": True,
                }
            }
            
            on_components_disable(mock_ctx, payload)
            
            # Verify enabled set to False
            assert mock_write.called
            written_registry = mock_write.call_args[0][0]
            assert written_registry["fixture_cpu"]["enabled"] is False
            
            # Verify state was published
            state_publishes = [
                call for call in mock_ctx.mqtt.publish.call_args_list
                if "state" in str(call[0][0])
            ]
            assert len(state_publishes) > 0


def test_enable_missing_component_id_returns_error(mock_ctx):
    """Test enable without component_id returns error."""
    payload = json.dumps({"request_id": "req123"})
    
    with patch("lucid_agent_core.core.handlers.load_registry") as mock_load:
        mock_load.return_value = {}
        
        on_components_enable(mock_ctx, payload)
        
        # Verify error result published
        result_payload = mock_ctx.mqtt.publish.call_args[0][1]
        result = json.loads(result_payload)
        assert result["ok"] is False
        assert "component_id is required" in result["error"]


def test_disable_missing_component_id_returns_error(mock_ctx):
    """Test disable without component_id returns error."""
    payload = json.dumps({"request_id": "req123"})
    
    with patch("lucid_agent_core.core.handlers.load_registry") as mock_load:
        mock_load.return_value = {}
        
        on_components_disable(mock_ctx, payload)
        
        # Verify error result published
        result_payload = mock_ctx.mqtt.publish.call_args[0][1]
        result = json.loads(result_payload)
        assert result["ok"] is False
        assert "component_id is required" in result["error"]


def test_enable_nonexistent_component_returns_error(mock_ctx):
    """Test enable for non-existent component returns error."""
    payload = json.dumps({"request_id": "req123", "component_id": "nonexistent"})
    
    with patch("lucid_agent_core.core.handlers.load_registry") as mock_load:
        mock_load.return_value = {}
        
        on_components_enable(mock_ctx, payload)
        
        # Verify error result published
        result_payload = mock_ctx.mqtt.publish.call_args[0][1]
        result = json.loads(result_payload)
        assert result["ok"] is False
        assert "component not found" in result["error"]
