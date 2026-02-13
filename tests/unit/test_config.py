from __future__ import annotations

import os

import pytest

from lucid_agent_core.config import ConfigError, load_config


def _clear_env(keys: list[str]) -> None:
    for k in keys:
        os.environ.pop(k, None)


REQ = ["MQTT_HOST", "MQTT_PORT", "AGENT_USERNAME", "AGENT_PASSWORD"]


def test_missing_required_env_raises(monkeypatch):
    _clear_env(REQ + ["AGENT_HEARTBEAT"])

    with pytest.raises(ConfigError) as exc:
        load_config(dotenv_enabled=False)

    # Ensure it names a missing key
    assert "Missing required environment variable" in str(exc.value)


def test_valid_env_loads(monkeypatch):
    _clear_env(REQ + ["AGENT_HEARTBEAT"])

    os.environ["MQTT_HOST"] = "10.0.0.1"
    os.environ["MQTT_PORT"] = "1883"
    os.environ["AGENT_USERNAME"] = "agent_1"
    os.environ["AGENT_PASSWORD"] = "pw"
    os.environ["AGENT_HEARTBEAT"] = "0"

    cfg = load_config(dotenv_enabled=False)

    assert cfg.mqtt_host == "10.0.0.1"
    assert cfg.mqtt_port == 1883
    assert cfg.agent_username == "agent_1"
    assert cfg.agent_password == "pw"
    assert cfg.agent_heartbeat_s == 0
    assert isinstance(cfg.agent_version, str)
    assert cfg.agent_version  # non-empty


def test_invalid_port_not_int_raises(monkeypatch):
    _clear_env(REQ + ["AGENT_HEARTBEAT"])

    os.environ["MQTT_HOST"] = "localhost"
    os.environ["MQTT_PORT"] = "not-a-number"
    os.environ["AGENT_USERNAME"] = "agent_1"
    os.environ["AGENT_PASSWORD"] = "pw"

    with pytest.raises(ConfigError) as exc:
        load_config(dotenv_enabled=False)

    assert "Invalid integer for MQTT_PORT" in str(exc.value)


@pytest.mark.parametrize("port", ["0", "65536", "-1"])
def test_port_out_of_range_raises(port: str):
    _clear_env(REQ + ["AGENT_HEARTBEAT"])

    os.environ["MQTT_HOST"] = "localhost"
    os.environ["MQTT_PORT"] = port
    os.environ["AGENT_USERNAME"] = "agent_1"
    os.environ["AGENT_PASSWORD"] = "pw"

    with pytest.raises(ConfigError) as exc:
        load_config(dotenv_enabled=False)

    assert "MQTT_PORT out of range" in str(exc.value)


def test_heartbeat_default_is_zero(monkeypatch):
    _clear_env(REQ + ["AGENT_HEARTBEAT"])

    os.environ["MQTT_HOST"] = "localhost"
    os.environ["MQTT_PORT"] = "1883"
    os.environ["AGENT_USERNAME"] = "agent_1"
    os.environ["AGENT_PASSWORD"] = "pw"

    cfg = load_config(dotenv_enabled=False)
    assert cfg.agent_heartbeat_s == 0


def test_heartbeat_negative_raises(monkeypatch):
    _clear_env(REQ + ["AGENT_HEARTBEAT"])

    os.environ["MQTT_HOST"] = "localhost"
    os.environ["MQTT_PORT"] = "1883"
    os.environ["AGENT_USERNAME"] = "agent_1"
    os.environ["AGENT_PASSWORD"] = "pw"
    os.environ["AGENT_HEARTBEAT"] = "-5"

    with pytest.raises(ConfigError) as exc:
        load_config(dotenv_enabled=False)

    assert "AGENT_HEARTBEAT must be >= 0" in str(exc.value)
