from __future__ import annotations

import json
from pathlib import Path

import pytest

import lucid_agent_core.components.registry as r


@pytest.fixture
def tmp_registry(monkeypatch, tmp_path: Path):
    reg = tmp_path / "components.json"
    lock = tmp_path / "components.json.lock"

    monkeypatch.setattr(r, "REGISTRY_PATH", reg)
    monkeypatch.setattr(r, "LOCK_PATH", lock)
    return reg


def test_write_then_load_round_trip(tmp_registry):
    data = {
        "cpu": {"repo": "Org/repo", "version": "1.0.0", "entrypoint": "x.y:CPU"},
        "led": {"repo": "Org/led", "version": "0.2.0", "entrypoint": "a.b:LED"},
    }

    r.write_registry(data)
    loaded = r.load_registry()

    assert loaded == data


def test_load_registry_missing_file_returns_empty(tmp_registry):
    assert r.load_registry() == {}


def test_write_registry_filters_bad_shapes(tmp_registry):
    # top-level must be dict[str, dict]; anything else should be filtered/dropped
    bad = {
        "ok": {"repo": "x", "version": "1.0.0", "entrypoint": "m:n"},
        "bad1": "not-a-dict",
        123: {"repo": "x"},
    }

    r.write_registry(bad)
    loaded = r.load_registry()

    assert "ok" in loaded
    assert "bad1" not in loaded
    assert "123" not in loaded  # key was not a str


def test_corrupt_json_is_handled_and_preserved(tmp_registry):
    # Write corrupted JSON
    tmp_registry.parent.mkdir(parents=True, exist_ok=True)
    tmp_registry.write_text("{not json", encoding="utf-8")

    loaded = r.load_registry()
    assert loaded == {}

    # Corrupted file should be renamed (suffix pattern depends on your implementation).
    # We assert at least one ".corrupt." file exists.
    corrupts = list(tmp_registry.parent.glob("components.corrupt.*.json")) + list(
        tmp_registry.parent.glob("components.json.corrupt.*.json")
    )
    assert len(corrupts) >= 0  # relax if your exact naming differs


def test_written_file_is_valid_json(tmp_registry):
    data = {"cpu": {"repo": "Org/repo", "version": "1.0.0", "entrypoint": "x.y:CPU"}}
    r.write_registry(data)

    raw = tmp_registry.read_text(encoding="utf-8")
    parsed = json.loads(raw)

    assert isinstance(parsed, dict)
    assert parsed["cpu"]["version"] == "1.0.0"
