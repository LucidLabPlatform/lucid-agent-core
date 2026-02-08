import pytest

from lucid_agent_core.components import registry


@pytest.mark.unit
def test_load_registry_missing_file_returns_empty(monkeypatch, tmp_path):
    path = tmp_path / "components.json"
    monkeypatch.setattr(registry, "REGISTRY_PATH", path)

    assert registry.load_registry() == {}


@pytest.mark.unit
def test_write_registry_is_atomic_and_loadable(monkeypatch, tmp_path):
    path = tmp_path / "components.json"
    monkeypatch.setattr(registry, "REGISTRY_PATH", path)

    data = {
        "led_strip": {
            "repo": "LucidLabPlatform/lucid-agent-led",
            "version": "0.1.0",
            "entrypoint": "lucid_agent_led.component:LedStripComponent",
        }
    }

    registry.write_registry(data)

    assert path.exists()
    assert registry.load_registry() == data


@pytest.mark.unit
def test_is_same_install():
    existing = {
        "repo": "LucidLabPlatform/lucid-agent-led",
        "version": "0.1.0",
        "entrypoint": "lucid_agent_led.component:LedStripComponent",
    }

    assert registry.is_same_install(
        existing,
        "LucidLabPlatform/lucid-agent-led",
        "0.1.0",
        "lucid_agent_led.component:LedStripComponent",
    )
    assert not registry.is_same_install(
        existing,
        "LucidLabPlatform/lucid-agent-led",
        "0.2.0",
        "lucid_agent_led.component:LedStripComponent",
    )

