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


# ---------------------------------------------------------------------------
# Drop-old-keep-new rate-limit behaviour
# ---------------------------------------------------------------------------


class _ManualExecutor:
    """Executor that returns real Future objects in PENDING state.

    Tests can call run_one() to execute a queued future synchronously, or
    start_one() to mark it RUNNING without executing fn (so the in-flight
    semaphore stays held while the future is uncancellable).
    """

    def __init__(self):
        self.queue: list = []  # list of (Future, callable)

    def submit(self, fn, *args):
        from concurrent.futures import Future
        f = Future()
        self.queue.append((f, lambda: fn(*args)))
        return f

    def run_one(self, idx: int = 0):
        f, fn = self.queue.pop(idx)
        if not f.set_running_or_notify_cancel():
            return
        try:
            f.set_result(fn())
        except BaseException as exc:
            f.set_exception(exc)

    def start_one(self, idx: int = 0):
        """Transition the queued future to RUNNING without executing fn."""
        f, _ = self.queue[idx]
        f.set_running_or_notify_cancel()

    def shutdown(self, *a, **k):
        pass


@pytest.fixture
def client_manual_exec(fake_paho_client, monkeypatch):
    """AgentMQTTClient bound to a _ManualExecutor with inflight_limit=1."""
    manual = _ManualExecutor()
    monkeypatch.setattr(
        "lucid_agent_core.mqtt.client.ThreadPoolExecutor",
        lambda *a, **k: manual,
    )
    c = AgentMQTTClient(
        host="localhost",
        port=1883,
        username="agent_1",
        password="pw",
        version="1.0.0",
        max_workers=1,
        heartbeat_interval_s=0,
        inflight_limit=1,
    )
    c._client = fake_paho_client
    c._manual = manual
    return c


def _result_topic_for(cmd_topic: str) -> str:
    return cmd_topic.replace("/cmd/", "/evt/", 1) + "/result"


def _published_results(fake_paho_client) -> list[dict]:
    """Return parsed JSON payloads for every publish call to a result topic."""
    out = []
    for call in fake_paho_client.publish.call_args_list:
        args, kwargs = call
        topic = args[0] if args else kwargs.get("topic")
        if topic and "/evt/" in topic and topic.endswith("/result"):
            payload = kwargs.get("payload", args[1] if len(args) > 1 else None)
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8")
            out.append({"topic": topic, "payload": json.loads(payload)})
    return out


def test_drop_old_when_capacity_full_and_cancellable_future_exists(
    client_manual_exec, fake_paho_client
):
    """A new command displaces a queued (PENDING) one and gets admitted."""
    c = client_manual_exec
    topics = TopicSchema("agent_1")
    cmd_topic = topics.cmd_ping()

    handler_calls = []
    c._handlers = {cmd_topic: lambda p: handler_calls.append(p)}

    # First message — acquires the only slot, future stays PENDING in queue.
    c._on_message(fake_paho_client, None, FakeMQTTMessage(
        cmd_topic, b'{"request_id":"old-1"}'
    ))
    assert len(c._manual.queue) == 1
    first_future, _ = c._manual.queue[0]
    assert first_future.cancelled() is False

    # Second message — semaphore is full; should cancel the queued future
    # and admit the new command.
    c._on_message(fake_paho_client, None, FakeMQTTMessage(
        cmd_topic, b'{"request_id":"new-2"}'
    ))

    assert first_future.cancelled() is True
    # Executor saw two submits; the second future is the admitted one.
    assert len(c._manual.queue) == 2
    new_future, _ = c._manual.queue[1]
    assert new_future is not first_future
    assert new_future.cancelled() is False
    # The agent-core pending deque tracks only the still-live entry.
    assert len(c._pending) == 1
    assert c._pending[0].future is new_future

    results = _published_results(fake_paho_client)
    cancelled = [r for r in results if r["payload"].get("request_id") == "old-1"]
    assert len(cancelled) == 1
    assert cancelled[0]["topic"] == _result_topic_for(cmd_topic)
    assert cancelled[0]["payload"]["ok"] is False
    assert "cancelled" in cancelled[0]["payload"]["error"].lower()


def test_drop_new_fallback_when_no_cancellable_future(
    client_manual_exec, fake_paho_client
):
    """If every in-flight future is RUNNING, the new command is dropped."""
    c = client_manual_exec
    topics = TopicSchema("agent_1")
    cmd_topic = topics.cmd_ping()

    c._handlers = {cmd_topic: lambda p: None}

    # First message — acquires slot, queued future.
    c._on_message(fake_paho_client, None, FakeMQTTMessage(
        cmd_topic, b'{"request_id":"running-1"}'
    ))
    # Mark the future RUNNING without executing fn — semaphore stays held.
    c._manual.start_one(0)
    running_future, _ = c._manual.queue[0]
    assert running_future.running() is True

    # Second message — must NOT cancel the running future; falls back to
    # publishing an "agent overloaded" failure for the new request_id.
    c._on_message(fake_paho_client, None, FakeMQTTMessage(
        cmd_topic, b'{"request_id":"new-2"}'
    ))

    assert running_future.cancelled() is False
    assert len(c._manual.queue) == 1  # only the still-running first future

    results = _published_results(fake_paho_client)
    new_failures = [r for r in results if r["payload"].get("request_id") == "new-2"]
    assert len(new_failures) == 1
    assert new_failures[0]["payload"]["ok"] is False
    assert "overloaded" in new_failures[0]["payload"]["error"].lower()


def test_cancellation_publishes_failure_with_distinct_error(
    client_manual_exec, fake_paho_client
):
    """The cancelled command's failure result uses a distinct error string."""
    c = client_manual_exec
    topics = TopicSchema("agent_1")
    cmd_topic = topics.cmd_ping()
    c._handlers = {cmd_topic: lambda p: None}

    c._on_message(fake_paho_client, None, FakeMQTTMessage(
        cmd_topic, b'{"request_id":"victim"}'
    ))
    c._on_message(fake_paho_client, None, FakeMQTTMessage(
        cmd_topic, b'{"request_id":"winner"}'
    ))

    results = _published_results(fake_paho_client)
    by_rid = {r["payload"]["request_id"]: r["payload"] for r in results}
    assert "victim" in by_rid
    assert by_rid["victim"]["ok"] is False
    assert by_rid["victim"]["error"] == "cancelled by newer command"
