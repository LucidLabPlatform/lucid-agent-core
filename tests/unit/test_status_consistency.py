"""
Tests for status/LWT consistency and schema validation.
"""
import json
from unittest.mock import MagicMock

import pytest

from lucid_agent_core.mqtt_client import AgentMQTTClient
from lucid_agent_core.mqtt_topics import TopicSchema


@pytest.fixture
def fake_paho_client(monkeypatch):
    fake = MagicMock()
    fake.is_connected.return_value = True

    def _ctor(*args, **kwargs):
        return fake

    monkeypatch.setattr("paho.mqtt.client.Client", _ctor)
    return fake


@pytest.fixture
def client(fake_paho_client, monkeypatch):
    class FakeExecutor:
        def __init__(self, *a, **k):
            pass
        def submit(self, fn, arg):
            fn(arg)
        def shutdown(self, *a, **k):
            pass

    monkeypatch.setattr("lucid_agent_core.mqtt_client.ThreadPoolExecutor", FakeExecutor)

    return AgentMQTTClient(
        host="localhost",
        port=1883,
        username="test",
        password="pw",
        version="1.0.0",
        heartbeat_interval_s=0,
    )


def test_lwt_matches_status_schema_exactly(client, fake_paho_client):
    """LWT must have state, connected_since_ts, uptime_s (no missing fields)."""
    client.connect()
    
    # Verify LWT was set with exact schema
    fake_paho_client.will_set.assert_called_once()
    args, kwargs = fake_paho_client.will_set.call_args
    
    topic = args[0]
    payload_str = kwargs.get("payload")
    
    assert topic == "lucid/agents/test/status"
    assert kwargs["retain"] is True
    assert kwargs["qos"] == 1
    
    payload = json.loads(payload_str)
    assert "state" in payload
    assert "connected_since_ts" in payload
    assert "uptime_s" in payload
    assert payload["state"] == "offline"
    assert len(payload) == 3  # No extra fields


def test_status_connected_since_ts_stable_across_updates(client, fake_paho_client, tmp_path):
    """connected_since_ts must not change on reconnect or heartbeat."""
    from lucid_agent_core.core.cmd_context import CoreCommandContext
    from lucid_agent_core.core.config_store import ConfigStore
    
    config_store = ConfigStore(str(tmp_path / "test_cfg.json"))
    config_store.load()
    
    ctx = CoreCommandContext(
        mqtt=client,
        topics=client.topics,
        agent_id="test",
        agent_version="1.0.0",
        config_store=config_store,
    )
    client.set_context(ctx)
    
    # First connect
    client.connect()
    client._on_connect(fake_paho_client, None, {}, 0)
    
    # Get initial connected_since_ts
    initial_ts = client._connected_since_ts
    assert initial_ts is not None
    
    # Simulate heartbeat
    import time
    time.sleep(0.1)
    client._publish_status("online")
    
    # Verify connected_since_ts unchanged
    assert client._connected_since_ts == initial_ts
    
    # Get status payload from last publish (payload is in kwargs)
    last_call = fake_paho_client.publish.call_args_list[-1]
    status_payload = json.loads(last_call[1]["payload"])
    assert status_payload["connected_since_ts"] == initial_ts
    assert status_payload["uptime_s"] > 0


def test_status_uptime_increases(client, fake_paho_client, tmp_path):
    """uptime_s must increase on subsequent status publishes."""
    from lucid_agent_core.core.cmd_context import CoreCommandContext
    from lucid_agent_core.core.config_store import ConfigStore
    
    config_store = ConfigStore(str(tmp_path / "test_cfg2.json"))
    config_store.load()
    
    ctx = CoreCommandContext(
        mqtt=client,
        topics=client.topics,
        agent_id="test",
        agent_version="1.0.0",
        config_store=config_store,
    )
    client.set_context(ctx)
    
    client.connect()
    client._on_connect(fake_paho_client, None, {}, 0)
    
    # Get initial status (payload is in kwargs)
    status_calls = [
        call for call in fake_paho_client.publish.call_args_list
        if len(call[0]) and call[0][0] == "lucid/agents/test/status"
    ]
    initial_status = json.loads(status_calls[-1][1]["payload"])
    initial_uptime = initial_status["uptime_s"]
    
    # Wait and publish again
    import time
    time.sleep(0.1)
    client._publish_status("online")
    
    # Get updated status (payload is in kwargs)
    status_calls = [
        call for call in fake_paho_client.publish.call_args_list
        if len(call[0]) and call[0][0] == "lucid/agents/test/status"
    ]
    updated_status = json.loads(status_calls[-1][1]["payload"])
    updated_uptime = updated_status["uptime_s"]
    
    assert updated_uptime > initial_uptime
