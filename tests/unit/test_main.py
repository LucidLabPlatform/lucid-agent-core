from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import lucid_agent_core.main as m


def test_parser_requires_subcommand():
    p = m.build_parser()
    with pytest.raises(SystemExit):
        p.parse_args([])


def test_version_flag_exits(monkeypatch, capsys):
    # argparse --version triggers SystemExit(0)
    monkeypatch.setattr(m, "get_version_string", lambda: "1.0.0")
    with pytest.raises(SystemExit) as exc:
        m.main(["--version"])
    assert exc.value.code == 0


def test_install_service_calls_installer(monkeypatch):
    called = {"n": 0}

    def fake_install(wheel_path=None):
        called["n"] += 1

    # main imports install_service inside the function
    monkeypatch.setattr("lucid_agent_core.installer.install_service", fake_install)

    m.main(["install-service"])
    assert called["n"] == 1


def test_run_exits_with_run_agent_code(monkeypatch):
    monkeypatch.setattr(m, "run_agent", lambda: 7)
    with pytest.raises(SystemExit) as exc:
        m.main(["run"])
    assert exc.value.code == 7


def test_run_agent_returns_1_on_mqtt_connect_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("LUCID_AGENT_BASE_DIR", str(tmp_path / "agent_base"))
    # Patch load_config to return a minimal config (avoid real env loading)
    fake_cfg = SimpleNamespace(
        mqtt_host="localhost",
        mqtt_port=1883,
        agent_username="agent_1",
        agent_password="pw",
        agent_version="1.0.0",
        agent_heartbeat_s=0,
    )
    monkeypatch.setattr("lucid_agent_core.config.load_config", lambda: fake_cfg)

    # Mock the default config path for ConfigStore
    import lucid_agent_core.core.config_store as cs
    original_init = cs.ConfigStore.__init__
    def mock_init(self, path=None):
        original_init(self, str(tmp_path / "test_config.json"))
    monkeypatch.setattr(cs.ConfigStore, "__init__", mock_init)

    # fake mqtt client
    fake_agent = MagicMock()
    fake_agent.connect.return_value = False

    monkeypatch.setattr("lucid_agent_core.mqtt_client.AgentMQTTClient", lambda *a, **k: fake_agent)

    code = m.run_agent()
    assert code == 1
    fake_agent.connect.assert_called_once()


def test_run_agent_shutdown_stops_components_before_mqtt_disconnect(monkeypatch, tmp_path):
    monkeypatch.setenv("LUCID_AGENT_BASE_DIR", str(tmp_path / "agent_base"))
    # Force immediate shutdown by monkeypatching threading.Event to be already set.
    import threading

    class SetEvent(threading.Event):
        def __init__(self):
            super().__init__()
            self.set()

    monkeypatch.setattr("threading.Event", SetEvent)

    # Patch load_config to return a minimal config
    fake_cfg = SimpleNamespace(
        mqtt_host="localhost",
        mqtt_port=1883,
        agent_username="agent_1",
        agent_password="pw",
        agent_version="1.0.0",
        agent_heartbeat_s=0,
    )
    monkeypatch.setattr("lucid_agent_core.config.load_config", lambda: fake_cfg)

    # Mock the default config path for ConfigStore
    import lucid_agent_core.core.config_store as cs
    original_init = cs.ConfigStore.__init__
    def mock_init(self, path=None):
        original_init(self, str(tmp_path / "test_config2.json"))
    monkeypatch.setattr(cs.ConfigStore, "__init__", mock_init)

    # fake agent
    fake_agent = MagicMock()
    fake_agent.connect.return_value = True
    monkeypatch.setattr("lucid_agent_core.mqtt_client.AgentMQTTClient", lambda *a, **k: fake_agent)

    # fake components - loader returns (components, load_results)
    stop_calls = []

    class C:
        def stop(self):
            stop_calls.append("stop")

    def fake_load_components(agent_id, base_topic, mqtt, config, *, registry=None):
        return ([C()], [SimpleNamespace(__dict__={})])

    monkeypatch.setattr(
        "lucid_agent_core.main.load_components",
        fake_load_components,
    )

    fake_agent.disconnect.side_effect = lambda: stop_calls.append("disconnect")

    code = m.run_agent()
    assert code == 0
    assert stop_calls[0] == "stop"
    assert stop_calls[-1] == "disconnect"
