from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from lucid_component_base import Component, ComponentContext
from lucid_agent_core.components.loader import load_components


class GoodComponent(Component):
    def __init__(self, context):
        super().__init__(context)
        self._started = False
        self._stopped = False

    @property
    def component_id(self) -> str:
        return "cpu"

    def _start(self) -> None:
        self._started = True

    def _stop(self) -> None:
        self._stopped = True


class NotAComponent:
    pass


@pytest.fixture
def loader_args():
    """Agent id, base_topic, mqtt, config for load_components."""
    fake_mqtt = MagicMock()
    fake_cfg = object()
    return {
        "agent_id": "agent_1",
        "base_topic": "lucid/agents/agent_1",
        "mqtt": fake_mqtt,
        "config": fake_cfg,
    }


def test_loads_and_autostarts_component(monkeypatch, loader_args):
    # Create a fake module with GoodComponent
    mod = types.SimpleNamespace(CPU=GoodComponent)

    def fake_import(name: str):
        assert name == "some.module"
        return mod

    monkeypatch.setattr("importlib.import_module", fake_import)

    registry = {
        "cpu": {
            "entrypoint": "some.module:CPU",
            "enabled": True,
            "auto_start": True,
        }
    }

    components, results = load_components(registry=registry, **loader_args)

    assert len(components) == 1
    assert results[0].ok is True
    assert results[0].started is True


def test_loads_but_does_not_start_when_auto_start_false(monkeypatch, loader_args):
    mod = types.SimpleNamespace(CPU=GoodComponent)
    monkeypatch.setattr("importlib.import_module", lambda name: mod)

    registry = {
        "cpu": {
            "entrypoint": "some.module:CPU",
            "enabled": True,
            "auto_start": False,
        }
    }

    components, results = load_components(registry=registry, **loader_args)

    assert len(components) == 1
    assert results[0].ok is True
    assert results[0].started is False


def test_skips_when_disabled(monkeypatch, loader_args):
    monkeypatch.setattr("importlib.import_module", lambda name: types.SimpleNamespace(CPU=GoodComponent))

    registry = {
        "cpu": {
            "entrypoint": "some.module:CPU",
            "enabled": False,
            "auto_start": True,
        }
    }

    components, results = load_components(registry=registry, **loader_args)

    assert components == []
    assert len(results) == 1
    assert results[0].ok is True  # "skipped but not error"
    assert results[0].started is False


def test_invalid_entrypoint_format_returns_error(loader_args):
    registry = {"cpu": {"entrypoint": "badformat"}}

    components, results = load_components(registry=registry, **loader_args)

    assert components == []
    assert results[0].ok is False
    assert "entrypoint" in (results[0].error or "")


def test_rejects_non_component_subclass(monkeypatch, loader_args):
    mod = types.SimpleNamespace(CPU=NotAComponent)
    monkeypatch.setattr("importlib.import_module", lambda name: mod)

    registry = {"cpu": {"entrypoint": "some.module:CPU"}}

    components, results = load_components(registry=registry, **loader_args)

    assert components == []
    assert results[0].ok is False
    assert "Component subclass" in (results[0].error or "")


def test_failure_is_isolated(monkeypatch, loader_args):
    class BadComponent(GoodComponent):
        def _start(self) -> None:
            raise RuntimeError("boom")

    mod = types.SimpleNamespace(CPU=BadComponent, OK=GoodComponent)
    monkeypatch.setattr("importlib.import_module", lambda name: mod)

    registry = {
        "cpu": {"entrypoint": "some.module:CPU", "auto_start": True},
        "ok": {"entrypoint": "some.module:OK", "auto_start": True},
    }

    components, results = load_components(registry=registry, **loader_args)

    # one fails, one succeeds
    assert len(components) == 1
    assert any(r.component_id == "cpu" and r.ok is False for r in results)
    assert any(r.component_id == "ok" and r.ok is True for r in results)
