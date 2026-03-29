from __future__ import annotations

import json
import logging

from lucid_agent_core.core.log_config import level_from_cfg_or_env
from lucid_agent_core.core.mqtt_log_handler import MQTTLogHandler
from lucid_agent_core.core.snapshots import build_cfg, build_cfg_logging


class _FakeConnectedClient:
    def is_connected(self) -> bool:
        return True


class _FakeMQTTClient:
    def __init__(self):
        self._client = _FakeConnectedClient()
        self.published: list[dict] = []

    def is_connected(self) -> bool:
        return self._client.is_connected()

    def publish(self, topic: str, payload: str, *, qos: int = 0, retain: bool = False) -> None:
        self.published.append(
            {
                "topic": topic,
                "payload": payload,
                "qos": qos,
                "retain": retain,
            }
        )


def test_build_cfg_returns_only_heartbeat_s():
    cfg = build_cfg({})
    assert "heartbeat_s" in cfg
    assert "logs_enabled" not in cfg
    assert "log_level" not in cfg
    assert "telemetry" not in cfg


def test_build_cfg_logging_returns_log_level_only():
    cfg = build_cfg_logging({})
    assert "log_level" in cfg
    assert cfg["log_level"] == "ERROR"
    assert "logs_enabled" not in cfg


def test_build_cfg_logging_reflects_stored_log_level():
    cfg = build_cfg_logging({"log_level": "INFO"})
    assert cfg["log_level"] == "INFO"
    assert "logs_enabled" not in cfg


def test_level_from_cfg_or_env_defaults_info(monkeypatch):
    monkeypatch.delenv("LUCID_LOG_LEVEL", raising=False)
    assert level_from_cfg_or_env(None) == logging.INFO


def _make_record(name: str = "lucid.test", level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg="test message",
        args=(),
        exc_info=None,
    )


def test_dropped_count_increments_on_emit_error():
    """If emit() fails internally, dropped_count goes up and no exception escapes."""
    fake_mqtt = _FakeMQTTClient()
    handler = MQTTLogHandler(fake_mqtt, "lucid/agents/agent_1/logs")

    # Break _build_line so emit() raises
    handler._build_line = lambda r: (_ for _ in ()).throw(RuntimeError("build failed"))

    record = _make_record()
    handler.emit(record)  # must not raise

    assert handler.dropped_count == 1


def test_dropped_count_increments_on_publish_failure():
    """If publish raises, dropped_count reflects the lost batch size."""
    fake_mqtt = _FakeMQTTClient()

    def _bad_publish(*a, **kw):
        raise OSError("broker gone")

    fake_mqtt.publish = _bad_publish

    handler = MQTTLogHandler(fake_mqtt, "lucid/agents/agent_1/logs")
    handler.emit(_make_record())
    handler.emit(_make_record())
    handler._publish_batch()  # triggers publish → raises → 2 lines dropped

    assert handler.dropped_count == 2


def test_dropped_count_property_is_readonly():
    fake_mqtt = _FakeMQTTClient()
    handler = MQTTLogHandler(fake_mqtt, "lucid/agents/agent_1/logs")
    assert handler.dropped_count == 0  # starts at zero


def test_mqtt_log_handler_publishes():
    fake_mqtt = _FakeMQTTClient()
    handler = MQTTLogHandler(fake_mqtt, "lucid/agents/agent_1/logs")

    record = logging.LogRecord(
        name="lucid.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=52,
        msg="hello %s",
        args=("mqtt",),
        exc_info=None,
        func="test_fn",
        sinfo=None,
    )
    handler.emit(record)
    handler._publish_batch()

    assert len(fake_mqtt.published) == 1
    payload = json.loads(fake_mqtt.published[0]["payload"])
    assert payload["count"] == 1

    line = payload["lines"][0]
    # Slim fields only
    for field in ("ts", "level", "logger", "message"):
        assert field in line
    # Dropped fields must be absent
    for field in ("module", "function", "file", "line", "thread", "process", "stack", "formatted"):
        assert field not in line
    assert line["level"] == "error"
    assert line["message"] == "hello mqtt"
    assert line["logger"] == "lucid.test"
