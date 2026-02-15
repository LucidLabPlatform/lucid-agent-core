"""
System installer for LUCID Agent Core (systemd + venv runtime).

Contract:
- Idempotent: safe to re-run.
- Creates lucid user if it doesn't exist with home /home/lucid and shell /bin/bash.
- Creates /home/lucid/lucid-agent-core/agent-core.env from packaged env.example and never overwrites it.
- Creates /home/lucid/lucid-agent-core/venv and installs into it.
- Supports local wheel installation via --wheel or LUCID_AGENT_CORE_WHEEL env var.
- Falls back to GitHub release URL if no local wheel provided.
- Writes/updates the systemd unit and enables the service.
- All files under /home/lucid with proper permissions.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import resources
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Optional


# =========================
# Constants
# =========================
SERVICE_NAME = "lucid-agent-core"
SYSTEM_USER = "lucid"

BASE_DIR = Path("/home/lucid/lucid-agent-core")
ENV_PATH = BASE_DIR / "agent-core.env"
VENV_DIR = BASE_DIR / "venv"

UNIT_PATH = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")


# =========================
# Utilities
# =========================
def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check)


def _ensure_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("This command must be run as root (sudo).")


def _ensure_user() -> None:
    """
    Ensure system user exists.
    
    Creates user 'lucid' with:
    - Home directory: /home/lucid
    - Shell: /bin/bash
    - Created with -m (create home) flag
    """
    try:
        _run(["id", SYSTEM_USER])
        print(f"User '{SYSTEM_USER}' already exists")
    except subprocess.CalledProcessError:
        print(f"Creating user '{SYSTEM_USER}'...")
        _run([
            "useradd",
            "-m",  # Create home directory
            "-d", f"/home/{SYSTEM_USER}",
            "-s", "/bin/bash",
            SYSTEM_USER,
        ])
        print(f"User '{SYSTEM_USER}' created successfully")


def _ensure_dirs() -> None:
    """
    Create required directories with secure permissions.
    
    Creates:
    - /home/lucid/lucid-agent-core/ (base)
    - /home/lucid/lucid-agent-core/venv
    - /home/lucid/lucid-agent-core/data
    - /home/lucid/lucid-agent-core/logs
    - /home/lucid/lucid-agent-core/run
    """
    for path, mode in [
        (BASE_DIR, 0o755),
        (BASE_DIR / "data", 0o750),
        (BASE_DIR / "logs", 0o750),
        (BASE_DIR / "run", 0o750),
    ]:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, mode)

    _run(["chown", "-R", f"{SYSTEM_USER}:{SYSTEM_USER}", str(BASE_DIR)])


def _ensure_env_file() -> None:
    """
    Create /home/lucid/lucid-agent-core/agent-core.env if it does not exist.
    """
    if ENV_PATH.exists():
        print(f"Environment file already exists: {ENV_PATH}")
        return

    try:
        env_example = resources.files("lucid_agent_core").joinpath("env.example")
        with env_example.open("r", encoding="utf-8") as src:
            content = src.read()
    except Exception:
        content = "# LUCID Agent Core environment variables\n"

    with ENV_PATH.open("w", encoding="utf-8") as dst:
        dst.write(content)

    os.chmod(ENV_PATH, 0o640)
    _run(["chown", f"{SYSTEM_USER}:{SYSTEM_USER}", str(ENV_PATH)])
    print(f"Created environment file: {ENV_PATH}")


def _detect_python() -> str:
    """
    Detect python3.11 or fallback to current interpreter.
    """
    py = shutil.which("python3.11")
    if py:
        return py

    # fallback to running interpreter
    if sys.version_info >= (3, 11):
        return sys.executable

    raise RuntimeError("Python 3.11+ required but not found.")


def _create_venv() -> None:
    if VENV_DIR.exists():
        print(f"Virtual environment already exists: {VENV_DIR}")
        return

    python_exec = _detect_python()
    print(f"Creating virtual environment using {python_exec}...")
    _run([python_exec, "-m", "venv", str(VENV_DIR)])

    _run(["chown", "-R", f"{SYSTEM_USER}:{SYSTEM_USER}", str(BASE_DIR)])
    print(f"Virtual environment created: {VENV_DIR}")


def _install_cli_into_venv(wheel_path: Optional[Path] = None) -> None:
    """
    Install lucid-agent-core into the venv.
    
    Args:
        wheel_path: Optional path to local wheel file.
                   If provided, installs from local wheel.
                   If None, installs from GitHub release URL.
    """
    pip = VENV_DIR / "bin" / "pip"

    if not pip.exists():
        raise FileNotFoundError(f"pip not found in venv: {pip}")

    if wheel_path:
        # Install from local wheel
        if not wheel_path.exists():
            raise FileNotFoundError(f"Wheel file not found: {wheel_path}")
        
        print(f"Installing from local wheel: {wheel_path}")
        _run([str(pip), "install", "--upgrade", str(wheel_path)])
    else:
        # Install from GitHub release
        version = pkg_version("lucid-agent-core")
        wheel_url = (
            f"https://github.com/LucidLabPlatform/lucid-agent-core/"
            f"releases/download/v{version}/"
            f"lucid_agent_core-{version}-py3-none-any.whl"
        )
        
        print(f"Installing from GitHub release: {wheel_url}")
        _run([str(pip), "install", "--upgrade", wheel_url])

    # Verify CLI exists
    cli = VENV_DIR / "bin" / "lucid-agent-core"
    if not cli.exists():
        raise RuntimeError("CLI executable missing after installation.")
    
    print(f"Installation successful: {cli}")


def _write_systemd_unit() -> None:
    """
    Install systemd unit from packaged template.
    """

    from importlib import resources

    try:
        unit_template = (
            resources.files("lucid_agent_core")
            .joinpath("systemd/lucid-agent-core.service")
        )

        with unit_template.open("r", encoding="utf-8") as f:
            content = f.read()

    except Exception as exc:
        raise RuntimeError(f"Failed to load packaged systemd unit: {exc}") from exc

    UNIT_PATH.write_text(content, encoding="utf-8")
    os.chmod(UNIT_PATH, 0o644)
    print(f"Systemd unit installed: {UNIT_PATH}")


def _reload_and_enable() -> None:
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", SERVICE_NAME])
    print(f"Service enabled: {SERVICE_NAME}")


# =========================
# Public entrypoint
# =========================
def install_service(wheel_path: Optional[Path] = None) -> None:
    """
    Install and enable lucid-agent-core systemd service.
    
    Args:
        wheel_path: Optional path to local wheel file.
                   If not provided, checks LUCID_AGENT_CORE_WHEEL env var.
                   If still not found, installs from GitHub release.
    """
    _ensure_root()
    
    # Check for wheel path from env var if not provided as argument
    if wheel_path is None:
        env_wheel = os.environ.get("LUCID_AGENT_CORE_WHEEL")
        if env_wheel:
            wheel_path = Path(env_wheel)
            print(f"Using wheel from LUCID_AGENT_CORE_WHEEL: {wheel_path}")
    
    _ensure_user()
    _ensure_dirs()
    _ensure_env_file()
    _create_venv()
    _install_cli_into_venv(wheel_path)
    _write_systemd_unit()
    _reload_and_enable()

    print("\n" + "="*60)
    print(f"✓ {SERVICE_NAME} installed and enabled successfully!")
    print("="*60)
    print(f"Base directory: {BASE_DIR}")
    print(f"Configuration: {ENV_PATH}")
    print(f"\nNext steps:")
    print(f"1. Edit {ENV_PATH} with your MQTT credentials")
    print(f"2. Start the service: sudo systemctl start {SERVICE_NAME}")
    print(f"3. Check status: sudo systemctl status {SERVICE_NAME}")
    print("="*60)
