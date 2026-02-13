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


def test_on_connect_subscribes_to_schema_topics_and_publishes_online(client, fake_paho_client):
    client.connect()
    # simulate successful connect callback
    client._on_connect(fake_paho_client, None, {}, 0)

    topics = TopicSchema("agent_1")

    # must subscribe to install command topic (schema-derived)
    fake_paho_client.subscribe.assert_any_call(topics.core_cmd_components_install(), qos=1)

    # must publish retained online status
    fake_paho_client.publish.assert_any_call(
        topics.status(),
        payload=ANY,
        qos=1,
        retain=True,
    )


def test_on_message_dispatches_known_topic(client, fake_paho_client, monkeypatch):
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
