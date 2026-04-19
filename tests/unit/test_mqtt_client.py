import json
from unittest.mock import ANY, MagicMock

import pytest

from lucid_agent_core.mqtt import AgentMQTTClient
from lucid_agent_core.mqtt_topics import TopicSchema


class _SuccessRC:
    """Minimal ReasonCode stand-in for VERSION2 callback tests (value=0 = success)."""

    def __eq__(self, other: object) -> bool:
        return int(other) == 0 if isinstance(other, int) else NotImplemented

    def __ne__(self, other: object) -> bool:
        return int(other) != 0 if isinstance(other, int) else NotImplemented

    def __str__(self) -> str:
        return "Success"


class FakeMQTTMessage:
    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


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
    submit_calls = []

    class FakeExecutor:
        def __init__(self, *a, **k):
            pass

        def submit(self, fn, *args):
            submit_calls.append((fn, *args))
            fn(*args)

        def shutdown(self, *a, **k):
            pass

    monkeypatch.setattr("lucid_agent_core.mqtt.client.ThreadPoolExecutor", FakeExecutor)

    c = AgentMQTTClient(
        host="localhost",
        port=1883,
        username="agent_1",
        password="pw",
        version="1.0.0",
        max_workers=2,
        heartbeat_interval_s=0,
    )
    c._submit_calls = submit_calls
    return c


def test_connect_sets_lwt_and_starts_loop(client, fake_paho_client):
    assert client.connect() is True

    topics = TopicSchema("agent_1")
    fake_paho_client.will_set.assert_called()
    args, kwargs = fake_paho_client.will_set.call_args
    assert args[0] == topics.status()
    payload = kwargs.get("payload", args[1] if len(args) > 1 else None)
    assert kwargs["retain"] is True
    assert kwargs["qos"] == 1
    obj = json.loads(payload)
    assert obj["state"] == "offline"
    # LWT is minimal: just state (topic already identifies the agent)

    fake_paho_client.connect.assert_called_with("localhost", 1883, keepalive=60)
    fake_paho_client.loop_start.assert_called_once()


def test_on_connect_subscribes_and_publishes_retained(client, fake_paho_client, tmp_path):
    from lucid_agent_core.core.cmd_context import CoreCommandContext
    from lucid_agent_core.core.config import ConfigStore

    config_store = ConfigStore(str(tmp_path / "test_cfg.json"))
    config_store.load()

    ctx = CoreCommandContext(
        mqtt=client,
        topics=client.topics,
        agent_id="agent_1",
        agent_version="1.0.0",
        config_store=config_store,
    )
    client.set_context(ctx)

    client.connect()
    client._on_connect(fake_paho_client, None, {}, _SuccessRC(), None)

    topics = TopicSchema("agent_1")

    fake_paho_client.subscribe.assert_any_call(topics.cmd_ping(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_restart(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_refresh(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_cfg_set(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_cfg_logging_set(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_cfg_telemetry_set(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_components_install(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_components_uninstall(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_components_enable(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_components_disable(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_components_upgrade(), qos=1)
    fake_paho_client.subscribe.assert_any_call(topics.cmd_core_upgrade(), qos=1)
    assert fake_paho_client.subscribe.call_count == 12

    publish_calls = fake_paho_client.publish.call_args_list
    retained_publishes = [c for c in publish_calls if c[1].get("retain") is True]
    assert len(retained_publishes) >= 3  # metadata, status, cfg (state published after components load)

    status_calls = [c for c in publish_calls if c[0][0] == topics.status()]
    assert len(status_calls) > 0
    status_payload = json.loads(status_calls[0][1].get("payload") or status_calls[0][0][1])
    assert status_payload["state"] == "online"
    assert "connected_since_ts" in status_payload
    assert "uptime_s" in status_payload


def test_on_message_dispatches_known_topic(client, fake_paho_client, tmp_path):
    from lucid_agent_core.core.cmd_context import CoreCommandContext
    from lucid_agent_core.core.config import ConfigStore

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

    called = {"n": 0, "payload": None}

    def handler(p: str) -> None:
        called["n"] += 1
        called["payload"] = p

    topics = TopicSchema("agent_1")
    client._handlers = {topics.cmd_ping(): handler}

    payload = '{"request_id":"abc"}'.encode("utf-8")
    msg = FakeMQTTMessage(topics.cmd_ping(), payload)

    client._on_message(fake_paho_client, None, msg)

    assert called["n"] == 1
    assert called["payload"] == '{"request_id":"abc"}'


def test_on_message_ignores_unknown_topic(client, fake_paho_client):
    called = {"n": 0}

    def handler(p: str) -> None:
        called["n"] += 1

    topics = TopicSchema("agent_1")
    client._handlers = {topics.cmd_ping(): handler}

    msg = FakeMQTTMessage("lucid/agents/agent_1/cmd/unknown", b"{}")
    client._on_message(fake_paho_client, None, msg)

    assert called["n"] == 0


def test_on_message_rejects_non_utf8_payload(client, fake_paho_client):
    called = {"n": 0}

    def handler(p: str) -> None:
        called["n"] += 1

    topics = TopicSchema("agent_1")
    client._handlers = {topics.cmd_ping(): handler}

    msg = FakeMQTTMessage(topics.cmd_ping(), b"\xff\xfe\xfd")
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


def test_add_component_handlers_subscribes_hyphenated_actions(client, fake_paho_client):
    class FakeComponent:
        component_id = "led_strip"

        def capabilities(self):
            return ["set-color", "effect/color-wipe", "effect/glow"]

        def _make_cmd_handler(self, action, method):
            return lambda p: method(p)

        def on_cmd_set_color(self, payload: str) -> None:
            pass

        def on_cmd_effect_color_wipe(self, payload: str) -> None:
            pass

        def on_cmd_effect_glow(self, payload: str) -> None:
            pass

    comp = FakeComponent()
    registry = {"led_strip": {"enabled": True}}
    client._client = fake_paho_client
    fake_paho_client.is_connected.return_value = True

    client.add_component_handlers([comp], registry)

    topics = TopicSchema("agent_1")
    expected_topics = [
        topics.component_cmd("led_strip", "set-color"),
        topics.component_cmd("led_strip", "effect/color-wipe"),
        topics.component_cmd("led_strip", "effect/glow"),
    ]
    for topic in expected_topics:
        assert topic in client._handlers
        fake_paho_client.subscribe.assert_any_call(topic, qos=1)


def test_subscribe_component_topics_subscribes_hyphenated_actions(client, fake_paho_client):
    class FakeComponent:
        def capabilities(self):
            return ["set-range-percent", "effect/rainbow-cycle"]

        def _make_cmd_handler(self, action, method):
            return lambda p: method(p)

        def on_cmd_set_range_percent(self, payload: str) -> None:
            pass

        def on_cmd_effect_rainbow_cycle(self, payload: str) -> None:
            pass

    comp = FakeComponent()
    client._client = fake_paho_client
    fake_paho_client.is_connected.return_value = True

    client._subscribe_component_topics(comp, "led_strip")

    topics = TopicSchema("agent_1")
    expected_topics = [
        topics.component_cmd("led_strip", "set-range-percent"),
        topics.component_cmd("led_strip", "effect/rainbow-cycle"),
    ]
    for topic in expected_topics:
        assert topic in client._handlers
        fake_paho_client.subscribe.assert_any_call(topic, qos=1)
