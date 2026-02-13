"""
System installer for LUCID Agent Core (systemd + venv runtime).

Contract:
- Idempotent: safe to re-run.
- Creates /etc/lucid/agent-core.env from packaged env.example and never overwrites it.
- Creates /opt/lucid/agent-core/venv and installs the running CLI version into it.
- Writes/updates the systemd unit and enables the service.
- Hardened systemd configuration.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import resources
from importlib.metadata import version as pkg_version
from pathlib import Path


# =========================
# Constants
# =========================
SERVICE_NAME = "lucid-agent-core"
SYSTEM_USER = "lucid"

ENV_DIR = Path("/etc/lucid")
ENV_PATH = ENV_DIR / "agent-core.env"

OPT_DIR = Path("/opt/lucid/agent-core")
VENV_DIR = OPT_DIR / "venv"

VAR_LIB = Path("/var/lib/lucid")
VAR_LOG = Path("/var/log/lucid")

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
    """
    try:
        _run(["id", SYSTEM_USER])
    except subprocess.CalledProcessError:
        _run([
            "useradd",
            "--system",
            "--create-home",
            "--home-dir", f"/home/{SYSTEM_USER}",
            "--shell", "/usr/sbin/nologin",
            SYSTEM_USER,
        ])


def _ensure_dirs() -> None:
    """
    Create required directories with secure permissions.
    """
    for path, mode in [
        (ENV_DIR, 0o750),
        (OPT_DIR, 0o755),
        (VAR_LIB, 0o750),
        (VAR_LOG, 0o750),
    ]:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, mode)

    _run(["chown", "-R", f"{SYSTEM_USER}:{SYSTEM_USER}", str(OPT_DIR)])
    _run(["chown", "-R", f"{SYSTEM_USER}:{SYSTEM_USER}", str(VAR_LIB)])
    _run(["chown", "-R", f"{SYSTEM_USER}:{SYSTEM_USER}", str(VAR_LOG)])


def _ensure_env_file() -> None:
    """
    Create /etc/lucid/agent-core.env if it does not exist.
    """
    if ENV_PATH.exists():
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
    _run(["chown", f"root:{SYSTEM_USER}", str(ENV_PATH)])


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
        return

    python_exec = _detect_python()
    _run([python_exec, "-m", "venv", str(VENV_DIR)])

    _run(["chown", "-R", f"{SYSTEM_USER}:{SYSTEM_USER}", str(OPT_DIR)])


def _install_cli_into_venv() -> None:
    """
    Install the exact version currently running into the venv.
    """
    version = pkg_version("lucid-agent-core")
    pip = VENV_DIR / "bin" / "pip"

    if not pip.exists():
        raise FileNotFoundError(f"pip not found in venv: {pip}")

    wheel_url = (
        f"https://github.com/LucidLabPlatform/lucid-agent-core/"
        f"releases/download/v{version}/"
        f"lucid_agent_core-{version}-py3-none-any.whl"
    )

    _run([str(pip), "install", "--upgrade", wheel_url])

    # Verify CLI exists
    cli = VENV_DIR / "bin" / "lucid-agent-core"
    if not cli.exists():
        raise RuntimeError("CLI executable missing after installation.")


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


def _reload_and_enable() -> None:
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", SERVICE_NAME])


# =========================
# Public entrypoint
# =========================
def install_service() -> None:
    """
    Install and enable lucid-agent-core systemd service.
    """
    _ensure_root()
    _ensure_user()
    _ensure_dirs()
    _ensure_env_file()
    _create_venv()
    _install_cli_into_venv()
    _write_systemd_unit()
    _reload_and_enable()

    print(f"{SERVICE_NAME} installed and enabled successfully.")
