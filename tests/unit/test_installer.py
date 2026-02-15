from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

import lucid_agent_core.installer as inst


@pytest.fixture
def sandbox_paths(monkeypatch, tmp_path: Path):
    """
    Redirect installer filesystem locations into a temp directory.
    """
    home = tmp_path / "home" / "lucid"
    base = home / "lucid-agent-core"
    systemd = tmp_path / "etc" / "systemd" / "system"

    monkeypatch.setattr(inst, "BASE_DIR", base)
    monkeypatch.setattr(inst, "ENV_PATH", base / "agent-core.env")
    monkeypatch.setattr(inst, "VENV_DIR", base / "venv")
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
        # Mimic CalledProcessError for "id lucid" when user doesn't exist
        if cmd[0] == "id" and cmd[1] == "lucid":
            # By default, user exists (no error)
            # Tests can override this by checking calls before test
            pass
        return MagicMock(returncode=0)

    monkeypatch.setattr(inst, "_run", fake_run)
    return calls


@pytest.fixture
def mock_run_user_missing(monkeypatch):
    """
    Mock _run where 'id lucid' raises CalledProcessError (user doesn't exist).
    """
    calls = []

    def fake_run(cmd, check=True):
        calls.append((tuple(cmd), check))
        if cmd[0] == "id" and cmd[1] == "lucid":
            raise subprocess.CalledProcessError(1, cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(inst, "_run", fake_run)
    return calls


def test_ensure_user_creates_user_if_missing(mock_run_user_missing):
    """Test that _ensure_user creates lucid user with correct parameters."""
    inst._ensure_user()

    # Should call: id lucid (which raises CalledProcessError)
    # Then call: useradd -m -d /home/lucid -s /bin/bash lucid
    cmds = [c[0] for c in mock_run_user_missing]
    
    assert ("id", "lucid") in cmds
    assert ("useradd", "-m", "-d", "/home/lucid", "-s", "/bin/bash", "lucid") in cmds


def test_ensure_user_skips_if_exists(mock_run):
    """Test that _ensure_user doesn't call useradd if user exists."""
    inst._ensure_user()

    cmds = [c[0] for c in mock_run]
    
    # Should only check id, not call useradd
    assert ("id", "lucid") in cmds
    assert not any("useradd" in cmd for cmd in cmds)


def test_install_cli_with_local_wheel(sandbox_paths, mock_run, monkeypatch, tmp_path):
    """Test that install uses local wheel when provided."""
    # Setup
    monkeypatch.setattr(inst.os, "geteuid", lambda: 0)
    
    # Create fake venv and pip
    venv_bin = inst.VENV_DIR / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    pip_path = venv_bin / "pip"
    pip_path.write_text("#!/bin/bash\necho pip")
    pip_path.chmod(0o755)
    
    # Create fake CLI after "install"
    cli_path = venv_bin / "lucid-agent-core"
    
    def fake_run_with_cli_creation(cmd, check=True):
        mock_run.append((tuple(cmd), check))
        # Create CLI when pip install is called
        if "pip" in cmd[0] and "install" in cmd:
            cli_path.write_text("#!/bin/bash\necho lucid-agent-core")
        return MagicMock(returncode=0)
    
    monkeypatch.setattr(inst, "_run", fake_run_with_cli_creation)
    
    # Create local wheel
    wheel_path = tmp_path / "lucid_agent_core-1.0.0-py3-none-any.whl"
    wheel_path.write_text("fake wheel content")
    
    # Run install
    inst._install_cli_into_venv(wheel_path)
    
    # Verify pip install was called with wheel path
    cmds = [c[0] for c in mock_run]
    expected_cmd = (str(pip_path), "install", "--upgrade", str(wheel_path))
    assert expected_cmd in cmds


def test_install_cli_from_github_when_no_wheel(sandbox_paths, mock_run, monkeypatch):
    """Test that install falls back to GitHub release when no wheel provided."""
    # Setup
    monkeypatch.setattr(inst.os, "geteuid", lambda: 0)
    monkeypatch.setattr(inst, "pkg_version", lambda x: "1.2.3")
    
    # Create fake venv and pip
    venv_bin = inst.VENV_DIR / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    pip_path = venv_bin / "pip"
    pip_path.write_text("#!/bin/bash\necho pip")
    pip_path.chmod(0o755)
    
    # Create fake CLI after "install"
    cli_path = venv_bin / "lucid-agent-core"
    
    def fake_run_with_cli_creation(cmd, check=True):
        mock_run.append((tuple(cmd), check))
        if "pip" in cmd[0] and "install" in cmd:
            cli_path.write_text("#!/bin/bash\necho lucid-agent-core")
        return MagicMock(returncode=0)
    
    monkeypatch.setattr(inst, "_run", fake_run_with_cli_creation)
    
    # Run install without wheel
    inst._install_cli_into_venv(None)
    
    # Verify pip install was called with GitHub URL
    cmds = [c[0] for c in mock_run]
    
    # Find the pip install command
    pip_install_cmd = None
    for cmd in cmds:
        if len(cmd) >= 4 and "pip" in cmd[0] and "install" in cmd:
            pip_install_cmd = cmd
            break
    
    assert pip_install_cmd is not None
    github_url = pip_install_cmd[-1]
    assert "github.com" in github_url
    assert "lucid-agent-core" in github_url
    assert "v1.2.3" in github_url


def test_install_service_with_wheel_argument(sandbox_paths, mock_run, monkeypatch, tmp_path):
    """Test full install_service with --wheel argument."""
    # Setup
    monkeypatch.setattr(inst.os, "geteuid", lambda: 0)
    monkeypatch.setattr(inst, "_ensure_user", lambda: None)
    monkeypatch.setattr(inst, "_ensure_dirs", lambda: None)
    
    # Mock env file creation
    def fake_ensure_env():
        inst.ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        inst.ENV_PATH.write_text("MQTT_HOST=test\n")
    monkeypatch.setattr(inst, "_ensure_env_file", fake_ensure_env)
    
    # Mock venv creation
    def fake_create_venv():
        inst.VENV_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(inst, "_create_venv", fake_create_venv)
    
    # Create local wheel
    wheel_path = tmp_path / "test.whl"
    wheel_path.write_text("fake wheel")
    
    # Mock install
    install_called_with = []
    def fake_install(wp):
        install_called_with.append(wp)
    monkeypatch.setattr(inst, "_install_cli_into_venv", fake_install)
    
    # Mock systemd
    monkeypatch.setattr(inst, "_write_systemd_unit", lambda: None)
    monkeypatch.setattr(inst, "_reload_and_enable", lambda: None)
    
    # Run
    inst.install_service(wheel_path)
    
    # Verify wheel path was passed to install
    assert len(install_called_with) == 1
    assert install_called_with[0] == wheel_path


def test_install_service_with_env_var_wheel(sandbox_paths, mock_run, monkeypatch, tmp_path):
    """Test that LUCID_AGENT_CORE_WHEEL env var is used."""
    # Setup
    monkeypatch.setattr(inst.os, "geteuid", lambda: 0)
    monkeypatch.setattr(inst, "_ensure_user", lambda: None)
    monkeypatch.setattr(inst, "_ensure_dirs", lambda: None)
    monkeypatch.setattr(inst, "_ensure_env_file", lambda: None)
    monkeypatch.setattr(inst, "_create_venv", lambda: None)
    monkeypatch.setattr(inst, "_write_systemd_unit", lambda: None)
    monkeypatch.setattr(inst, "_reload_and_enable", lambda: None)
    
    # Create local wheel
    wheel_path = tmp_path / "env_test.whl"
    wheel_path.write_text("fake wheel")
    
    # Set env var
    monkeypatch.setenv("LUCID_AGENT_CORE_WHEEL", str(wheel_path))
    
    # Mock install
    install_called_with = []
    def fake_install(wp):
        install_called_with.append(wp)
    monkeypatch.setattr(inst, "_install_cli_into_venv", fake_install)
    
    # Run without explicit wheel argument
    inst.install_service(None)
    
    # Verify env var wheel was used
    assert len(install_called_with) == 1
    assert install_called_with[0] == wheel_path


def test_install_service_github_fallback_when_no_wheel(sandbox_paths, mock_run, monkeypatch):
    """Test that GitHub URL is used when no wheel provided."""
    # Setup
    monkeypatch.setattr(inst.os, "geteuid", lambda: 0)
    monkeypatch.setattr(inst, "_ensure_user", lambda: None)
    monkeypatch.setattr(inst, "_ensure_dirs", lambda: None)
    monkeypatch.setattr(inst, "_ensure_env_file", lambda: None)
    monkeypatch.setattr(inst, "_create_venv", lambda: None)
    monkeypatch.setattr(inst, "_write_systemd_unit", lambda: None)
    monkeypatch.setattr(inst, "_reload_and_enable", lambda: None)
    
    # Mock install
    install_called_with = []
    def fake_install(wp):
        install_called_with.append(wp)
    monkeypatch.setattr(inst, "_install_cli_into_venv", fake_install)
    
    # Run without wheel
    inst.install_service(None)
    
    # Verify None was passed (GitHub fallback)
    assert len(install_called_with) == 1
    assert install_called_with[0] is None


def test_env_file_not_overwritten_if_exists(sandbox_paths, mock_run, monkeypatch):
    """Test that existing env file is preserved."""
    monkeypatch.setattr(inst.os, "geteuid", lambda: 0)
    
    inst.ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    inst.ENV_PATH.write_text("EXISTING_CONFIG\n")
    
    # Run ensure_env_file
    inst._ensure_env_file()
    
    # Verify not overwritten
    assert inst.ENV_PATH.read_text() == "EXISTING_CONFIG\n"


def test_detect_python_prefers_python311(monkeypatch):
    """Test that _detect_python prefers python3.11 if available."""
    monkeypatch.setattr(inst.shutil, "which", lambda x: "/usr/bin/python3.11" if x == "python3.11" else None)
    
    result = inst._detect_python()
    
    assert result == "/usr/bin/python3.11"


def test_detect_python_fallback_to_current(monkeypatch):
    """Test that _detect_python falls back to current interpreter."""
    monkeypatch.setattr(inst.shutil, "which", lambda x: None)
    monkeypatch.setattr(inst.sys, "version_info", (3, 11, 0))
    monkeypatch.setattr(inst.sys, "executable", "/usr/bin/python3")
    
    result = inst._detect_python()
    
    assert result == "/usr/bin/python3"


def test_reload_and_enable_calls_systemctl(mock_run):
    """Test that systemctl commands are called correctly."""
    inst._reload_and_enable()
    
    cmds = [c[0] for c in mock_run]
    assert ("systemctl", "daemon-reload") in cmds
    assert ("systemctl", "enable", "lucid-agent-core") in cmds
