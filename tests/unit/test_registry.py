from __future__ import annotations

import json
from pathlib import Path

import pytest

import lucid_agent_core.components.registry as r
from lucid_agent_core.paths import build_paths, reset_paths, set_paths


@pytest.fixture
def tmp_registry(tmp_path: Path):
    """Use tmp_path as base_dir so registry reads/writes under tmp_path/data/."""
    paths = build_paths(tmp_path)
    set_paths(paths)
    try:
        yield paths.registry_path
    finally:
        reset_paths()


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

    # Corrupted file should be renamed to components_registry.corrupt.<ts>.json
    corrupts = list(tmp_registry.parent.glob("components_registry.corrupt.*.json"))
    assert len(corrupts) >= 1


def test_written_file_is_valid_json(tmp_registry):
    data = {"cpu": {"repo": "Org/repo", "version": "1.0.0", "entrypoint": "x.y:CPU"}}
    r.write_registry(data)

    raw = tmp_registry.read_text(encoding="utf-8")
    parsed = json.loads(raw)

    assert isinstance(parsed, dict)
    assert parsed["cpu"]["version"] == "1.0.0"
