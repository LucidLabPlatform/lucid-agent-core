from __future__ import annotations

from lucid_agent_core.core.config_store import ConfigStore


def test_apply_set_general_only_updates_cfg_domain(tmp_path, monkeypatch):
    monkeypatch.setenv("LUCID_AGENT_BASE_DIR", str(tmp_path))
    store = ConfigStore()
    store.load()

    new_cfg, result = store.apply_set_general(
        {"request_id": "r1", "set": {"heartbeat_s": 30}}
    )
    assert result["ok"] is True
    assert new_cfg["heartbeat_s"] == 30

    _, bad = store.apply_set_general({"request_id": "r2", "set": {"log_level": "INFO"}})
    assert bad["ok"] is False
    assert "unknown config key" in bad["error"]


def test_apply_set_logging_only_updates_logging_domain(tmp_path, monkeypatch):
    monkeypatch.setenv("LUCID_AGENT_BASE_DIR", str(tmp_path))
    store = ConfigStore()
    store.load()

    new_cfg, result = store.apply_set_logging(
        {"request_id": "r1", "set": {"log_level": "INFO"}}
    )
    assert result["ok"] is True
    assert new_cfg["log_level"] == "INFO"

    _, bad = store.apply_set_logging({"request_id": "r2", "set": {"heartbeat_s": 30}})
    assert bad["ok"] is False
    assert "unknown config key" in bad["error"]


def test_apply_set_telemetry_updates_metric_domain(tmp_path, monkeypatch):
    monkeypatch.setenv("LUCID_AGENT_BASE_DIR", str(tmp_path))
    store = ConfigStore()
    store.load()

    new_cfg, result = store.apply_set_telemetry(
        {
            "request_id": "r1",
            "set": {
                "cpu_percent": {
                    "enabled": True,
                    "interval_s": 3,
                    "change_threshold_percent": 1.5,
                }
            },
        }
    )
    assert result["ok"] is True
    metrics = new_cfg["telemetry"]["metrics"]
    assert metrics["cpu_percent"]["enabled"] is True
    assert metrics["cpu_percent"]["interval_s"] == 3
    assert metrics["cpu_percent"]["change_threshold_percent"] == 1.5

    _, bad = store.apply_set_telemetry(
        {"request_id": "r2", "set": {"cpu_percent": {"interval_s": 0}}}
    )
    assert bad["ok"] is False
    assert "interval_s must be integer >= 1" in bad["error"]
