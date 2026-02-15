"""
Tests for paths module.
"""

import os
from pathlib import Path

import pytest

from lucid_agent_core.paths import build_paths, ensure_dirs, get_paths, reset_paths, set_paths


def test_build_paths_default():
    """Test that build_paths creates correct default structure."""
    paths = build_paths()

    assert paths.base_dir == Path("/home/lucid/lucid-agent-core")
    assert paths.venv_dir == Path("/home/lucid/lucid-agent-core/venv")
    assert paths.data_dir == Path("/home/lucid/lucid-agent-core/data")
    assert paths.registry_path == Path("/home/lucid/lucid-agent-core/data/components_registry.json")
    assert paths.config_path == Path("/home/lucid/lucid-agent-core/data/core_config.json")
    assert paths.log_dir == Path("/home/lucid/lucid-agent-core/logs")
    assert paths.runtime_dir == Path("/home/lucid/lucid-agent-core/run")


def test_build_paths_custom_base():
    """Test that build_paths accepts custom base directory."""
    custom_base = Path("/tmp/test-lucid")
    paths = build_paths(custom_base)

    assert paths.base_dir == custom_base
    assert paths.venv_dir == custom_base / "venv"
    assert paths.data_dir == custom_base / "data"
    assert paths.registry_path == custom_base / "data" / "components_registry.json"
    assert paths.config_path == custom_base / "data" / "core_config.json"


def test_build_paths_env_var_override(monkeypatch):
    """Test that LUCID_AGENT_BASE_DIR env var overrides default."""
    custom_base = "/tmp/env-override"
    monkeypatch.setenv("LUCID_AGENT_BASE_DIR", custom_base)

    paths = build_paths()

    assert paths.base_dir == Path(custom_base)


def test_paths_properties():
    """Test that path properties work correctly."""
    paths = build_paths(Path("/tmp/test"))

    assert paths.pip_path == Path("/tmp/test/venv/bin/pip")
    assert paths.python_path == Path("/tmp/test/venv/bin/python")
    assert paths.cli_path == Path("/tmp/test/venv/bin/lucid-agent-core")
    assert paths.registry_lock_path == Path("/tmp/test/data/components_registry.json.lock")
    assert paths.config_lock_path == Path("/tmp/test/data/core_config.json.lock")
    assert paths.restart_sentinel_path == Path("/tmp/test/run/restart.requested")


def test_ensure_dirs_creates_structure(tmp_path):
    """Test that ensure_dirs creates all required directories."""
    base = tmp_path / "lucid-test"
    paths = build_paths(base)

    ensure_dirs(paths)

    assert paths.base_dir.exists()
    assert paths.base_dir.is_dir()
    assert paths.venv_dir.exists()
    assert paths.data_dir.exists()
    assert paths.log_dir.exists()
    assert paths.runtime_dir.exists()


def test_ensure_dirs_idempotent(tmp_path):
    """Test that ensure_dirs can be called multiple times safely."""
    base = tmp_path / "lucid-test"
    paths = build_paths(base)

    ensure_dirs(paths)
    ensure_dirs(paths)  # Second call should not fail

    assert paths.base_dir.exists()


def test_get_paths_singleton():
    """Test that get_paths returns same instance."""
    reset_paths()  # Ensure clean state

    paths1 = get_paths()
    paths2 = get_paths()

    assert paths1 is paths2


def test_set_paths_override():
    """Test that set_paths allows custom paths."""
    reset_paths()

    custom_paths = build_paths(Path("/custom/base"))
    set_paths(custom_paths)

    paths = get_paths()
    assert paths is custom_paths
    assert paths.base_dir == Path("/custom/base")


def test_reset_paths():
    """Test that reset_paths clears singleton."""
    # Set custom paths
    custom_paths = build_paths(Path("/custom/base"))
    set_paths(custom_paths)

    # Reset
    reset_paths()

    # Next get_paths should create new instance with defaults
    paths = get_paths()
    assert paths is not custom_paths
    assert paths.base_dir == Path("/home/lucid/lucid-agent-core")
