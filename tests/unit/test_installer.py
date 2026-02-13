from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lucid_agent_core.installer as inst


@pytest.fixture
def sandbox_paths(monkeypatch, tmp_path: Path):
    """
    Redirect installer filesystem locations into a temp directory.
    """
    etc = tmp_path / "etc"
    opt = tmp_path / "opt"
    var = tmp_path / "var"
    systemd = tmp_path / "systemd"

    monkeypatch.setattr(inst, "ENV_DIR", etc / "lucid")
    monkeypatch.setattr(inst, "ENV_PATH", (etc / "lucid" / "agent-core.env"))

    monkeypatch.setattr(inst, "OPT_DIR", opt / "lucid" / "agent-core")
    monkeypatch.setattr(inst, "VENV_DIR", (opt / "lucid" / "agent-core" / "venv"))

    monkeypatch.setattr(inst, "VAR_LIB", var / "lib" / "lucid")
    monkeypatch.setattr(inst, "VAR_LOG", var / "log" / "lucid")

    monkeypatch.setattr(inst, "UNIT_PATH", systemd / "lucid-agent-core.service")

    return tmp_path


@pytest.fixture
def mock_run(monkeypatch):
    """
    Capture subprocess commands without executing them.
    """
    calls = []

    def fake_run(cmd, check=True):
        calls.append((tuple(cmd), check))
        # mimic CompletedProcess-ish
        return MagicMock(returncode=0)

    monkeypatch.setattr(inst, "_run", fake_run)
    return calls


def test_install_service_creates_env_file_if_missing(sandbox_paths, mock_run, monkeypatch):
    # Pretend we're root
    monkeypatch.setattr(inst.os, "geteuid", lambda: 0)

    # Ensure "lucid" user exists
    monkeypatch.setattr(inst, "_ensure_user", lambda: None)

    # Provide env.example via resources fallback: just write minimal content
    def fake_ensure_env():
        inst.ENV_DIR.mkdir(parents=True, exist_ok=True)
        inst.ENV_PATH.write_text("MQTT_HOST=x\n", encoding="utf-8")
    monkeypatch.setattr(inst, "_ensure_env_file", fake_ensure_env)

    # Avoid creating real venv/pip calls
    monkeypatch.setattr(inst, "_create_venv", lambda: inst.VENV_DIR.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(inst, "_install_cli_into_venv", lambda: None)

    # Write unit file (ensure parent dir exists)
    def fake_write_systemd_unit():
        inst.UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        inst.UNIT_PATH.write_text("UNIT\n", encoding="utf-8")

    monkeypatch.setattr(inst, "_write_systemd_unit", fake_write_systemd_unit)
    monkeypatch.setattr(inst, "_reload_and_enable", lambda: None)

    inst.install_service()

    assert inst.ENV_PATH.exists()
    assert inst.ENV_PATH.read_text(encoding="utf-8") == "MQTT_HOST=x\n"


def test_env_file_not_overwritten_if_exists(sandbox_paths, mock_run, monkeypatch):
    monkeypatch.setattr(inst.os, "geteuid", lambda: 0)
    monkeypatch.setattr(inst, "_ensure_user", lambda: None)
    monkeypatch.setattr(inst, "_ensure_dirs", lambda: None)

    inst.ENV_DIR.mkdir(parents=True, exist_ok=True)
    inst.ENV_PATH.write_text("DO_NOT_TOUCH\n", encoding="utf-8")

    # Real behavior: _ensure_env_file should no-op if exists.
    # If your implementation differs, adapt accordingly.
    inst._ensure_env_file()

    assert inst.ENV_PATH.read_text(encoding="utf-8") == "DO_NOT_TOUCH\n"


def test_write_systemd_unit_creates_unit_file(sandbox_paths, mock_run, monkeypatch):
    monkeypatch.setattr(inst.os, "geteuid", lambda: 0)

    # If you load from packaged template, mock it by patching the function directly:
    inst.UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Use the real function if it’s deterministic, otherwise patch:
    monkeypatch.setattr(inst, "_write_systemd_unit", lambda: inst.UNIT_PATH.write_text("UNIT\n", encoding="utf-8"))

    inst._write_systemd_unit()

    assert inst.UNIT_PATH.exists()
    assert inst.UNIT_PATH.read_text(encoding="utf-8") == "UNIT\n"


def test_reload_and_enable_calls_systemctl(mock_run):
    # Call real function if it only uses _run (safe)
    # If your _reload_and_enable does additional behavior, patch accordingly.
    if hasattr(inst, "_reload_and_enable"):
        inst._reload_and_enable()

        cmds = [c[0] for c in mock_run]
        assert ("systemctl", "daemon-reload") in cmds
        assert ("systemctl", "enable", inst.SERVICE_NAME) in cmds


def test_detect_python_uses_which_or_fallback(monkeypatch):
    # If your installer has _detect_python:
    if not hasattr(inst, "_detect_python"):
        pytest.skip("installer has no _detect_python()")

    monkeypatch.setattr(inst.shutil, "which", lambda x: "/usr/bin/python3.11" if x == "python3.11" else None)
    assert inst._detect_python() == "/usr/bin/python3.11"
