from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from lucid_agent_core.core.log_config import level_from_cfg_or_env
from lucid_agent_core.core.mqtt_log_handler import MQTTLogHandler
from lucid_agent_core.core.snapshots import build_cfg


class _FakeConfigStore:
    def __init__(self, cfg: dict):
        self._cfg = cfg

    def get_cached(self) -> dict:
        return dict(self._cfg)


class _FakeConnectedClient:
    def is_connected(self) -> bool:
        return True


class _FakeMQTTClient:
    def __init__(self, cfg: dict):
        self._ctx = SimpleNamespace(config_store=_FakeConfigStore(cfg))
        self._client = _FakeConnectedClient()
        self.published: list[dict] = []

    def publish(self, topic: str, payload: str, *, qos: int = 0, retain: bool = False) -> None:
        self.published.append(
            {
                "topic": topic,
                "payload": payload,
                "qos": qos,
                "retain": retain,
            }
        )


def test_build_cfg_defaults_enable_logs_and_debug_level():
    cfg = build_cfg({})
    assert cfg["logs_enabled"] is True
    assert cfg["log_level"] == "DEBUG"


def test_level_from_cfg_or_env_defaults_debug(monkeypatch):
    monkeypatch.delenv("LUCID_LOG_LEVEL", raising=False)
    assert level_from_cfg_or_env(None) == logging.DEBUG


def test_mqtt_log_handler_publishes_structured_line_when_enabled_by_default():
    fake_mqtt = _FakeMQTTClient(cfg={})  # Missing logs_enabled should default to enabled
    handler = MQTTLogHandler(fake_mqtt, "lucid/agents/agent_1/logs")

    record = logging.LogRecord(
        name="lucid.test",
        level=logging.INFO,
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
    required_fields = [
        "ts",
        "level",
        "logger",
        "module",
        "function",
        "file",
        "line",
        "thread",
        "process",
        "message",
    ]
    for field in required_fields:
        assert field in line
    assert line["level"] == "info"
    assert line["message"] == "hello mqtt"
    assert line["logger"] == "lucid.test"


def test_mqtt_log_handler_respects_logs_enabled_false():
    fake_mqtt = _FakeMQTTClient(cfg={"logs_enabled": False})
    handler = MQTTLogHandler(fake_mqtt, "lucid/agents/agent_1/logs")

    record = logging.LogRecord(
        name="lucid.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=97,
        msg="suppressed",
        args=(),
        exc_info=None,
        func="test_fn",
        sinfo=None,
    )
    handler.emit(record)
    handler._publish_batch()

    assert fake_mqtt.published == []
