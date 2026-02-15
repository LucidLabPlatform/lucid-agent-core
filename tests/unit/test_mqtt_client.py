import json
from unittest.mock import ANY, MagicMock

import pytest

from lucid_agent_core.mqtt_client import AgentMQTTClient
from lucid_agent_core.mqtt_topics import TopicSchema


class FakeMQTTMessage:
    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


@pytest.fixture
def fake_paho_client(monkeypatch):
    """
    Patch paho.mqtt.client.Client to return a controllable fake.
    """
    fake = MagicMock()
    fake.is_connected.return_value = True

    def _ctor(*args, **kwargs):
        return fake

    monkeypatch.setattr("paho.mqtt.client.Client", _ctor)
    return fake


@pytest.fixture
def client(fake_paho_client, monkeypatch):
    # Patch executor to make submit synchronous and observable
    submit_calls = []

    class FakeExecutor:
        def __init__(self, *a, **k):
            pass

        def submit(self, fn, arg):
            submit_calls.append((fn, arg))
            # execute immediately
            fn(arg)

        def shutdown(self, *a, **k):
            pass

    monkeypatch.setattr("lucid_agent_core.mqtt_client.ThreadPoolExecutor", FakeExecutor)

    c = AgentMQTTClient(
        host="localhost",
        port=1883,
        username="agent_1",
        password="pw",
        version="1.0.0",
        max_workers=2,
        heartbeat_interval_s=0,
    )
    c._submit_calls = submit_calls  # test hook
    return c


def test_connect_sets_lwt_and_starts_loop(client, fake_paho_client):
    assert client.connect() is True

    topics = TopicSchema("agent_1")

    # will_set called correctly on status() with retained offline payload
    fake_paho_client.will_set.assert_called()
    args, kwargs = fake_paho_client.will_set.call_args
    assert args[0] == topics.status()
    payload = kwargs.get("payload", args[1] if len(args) > 1 else None)
    assert kwargs["retain"] is True
    assert kwargs["qos"] == 1
    obj = json.loads(payload)
    assert obj["state"] == "offline"
    assert "ts" in obj
    assert obj["version"] == "1.0.0"

    fake_paho_client.connect.assert_called_with("localhost", 1883, keepalive=60)
    fake_paho_client.loop_start.assert_called_once()


def test_on_connect_subscribes_to_schema_topics_and_publishes_online(client, fake_paho_client, tmp_path):
    from lucid_agent_core.core.cmd_context import CoreCommandContext
    from lucid_agent_core.core.config_store import ConfigStore
    from unittest.mock import MagicMock

    # Set up context before connect
    config_store = ConfigStore(str(tmp_path / "test_cfg.json"))
    config_store.load()  # Initialize cache
    
    ctx = CoreCommandContext(
        mqtt=client,
        topics=client.topics,
        agent_id="agent_1",
        agent_version="1.0.0",
        config_store=config_store,
    )
    client.set_context(ctx)

    client.connect()
    # simulate successful connect callback
    client._on_connect(fake_paho_client, None, {}, 0)

    topics = TopicSchema("agent_1")

    # Verify subscriptions to all 4 command topics
    fake_paho_client.subscribe.assert_any_call(topics.core_cmd_components_install(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.core_cmd_components_uninstall(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.core_cfg_set(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.core_cmd_refresh(), qos=1)
    assert fake_paho_client.subscribe.call_count == 4

    # Verify retained snapshots were published (via ctx.publish which calls client.publish)
    # Check that publish was called with retain=True for retained topics
    publish_calls = fake_paho_client.publish.call_args_list
    retained_topics = [
        topics.status(),
        topics.core_metadata(),
        topics.core_state(),
        topics.core_components(),
        topics.core_cfg_state(),
    ]
    
    # Verify at least 5 retained publishes happened
    retained_publishes = [
        call for call in publish_calls
        if call[1].get("retain") is True  # Check kwargs
    ]
    assert len(retained_publishes) >= 5, f"Expected at least 5 retained publishes, got {len(retained_publishes)}"
    
    # Verify status payload includes schema and agent_id
    status_publishes = [
        call for call in publish_calls
        if call[0][0] == topics.status()  # First positional arg is topic
    ]
    assert len(status_publishes) > 0, "Status not published"
    status_payload_str = status_publishes[0][1].get("payload") or status_publishes[0][0][1]
    status_payload = json.loads(status_payload_str)
    assert status_payload["agent_id"] == "agent_1"
    assert status_payload["state"] == "online"


def test_on_message_dispatches_known_topic(client, fake_paho_client, monkeypatch, tmp_path):
    from lucid_agent_core.core.cmd_context import CoreCommandContext
    from lucid_agent_core.core.config_store import ConfigStore

    # Set up context so messages are not rejected
    config_store = ConfigStore(str(tmp_path / "test_cfg2.json"))
    config_store.load()
    
    ctx = CoreCommandContext(
        mqtt=client,
        topics=client.topics,
        agent_id="agent_1",
        agent_version="1.0.0",
        config_store=config_store,
    )
    client.set_context(ctx)

    # Replace handler with spy
    called = {"n": 0, "payload": None}

    def handler(p: str) -> None:
        called["n"] += 1
        called["payload"] = p

    topics = TopicSchema("agent_1")
    client._handlers = {topics.core_cmd_components_install(): handler}

    payload = '{"hello":"world"}'.encode("utf-8")
    msg = FakeMQTTMessage(topics.core_cmd_components_install(), payload)

    client._on_message(fake_paho_client, None, msg)

    assert called["n"] == 1
    assert called["payload"] == '{"hello":"world"}'


def test_on_message_ignores_unknown_topic(client, fake_paho_client):
    called = {"n": 0}

    def handler(p: str) -> None:
        called["n"] += 1

    topics = TopicSchema("agent_1")
    client._handlers = {topics.core_cmd_components_install(): handler}

    msg = FakeMQTTMessage("lucid/agents/agent_1/core/cmd/unknown", b"{}")
    client._on_message(fake_paho_client, None, msg)

    assert called["n"] == 0


def test_on_message_rejects_non_utf8_payload(client, fake_paho_client):
    called = {"n": 0}

    def handler(p: str) -> None:
        called["n"] += 1

    topics = TopicSchema("agent_1")
    client._handlers = {topics.core_cmd_components_install(): handler}

    msg = FakeMQTTMessage(topics.core_cmd_components_install(), b"\xff\xfe\xfd")
    client._on_message(fake_paho_client, None, msg)

    assert called["n"] == 0


def test_disconnect_publishes_offline_and_stops_loop(client, fake_paho_client):
    client.connect()
    client.disconnect()

    topics = TopicSchema("agent_1")
    fake_paho_client.publish.assert_any_call(
        topics.status(),
        payload=ANY,
        qos=1,
        retain=True,
    )
    fake_paho_client.loop_stop.assert_called_once()
    fake_paho_client.disconnect.assert_called_once()
