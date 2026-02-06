"""
System installer for LUCID Agent Core (systemd + venv runtime).

Usage:
  sudo lucid-agent-core install-service

Contract:
- Idempotent: safe to re-run.
- Creates /etc/lucid/agent-core.env from packaged env.example and never overwrites it.
- Creates /opt/lucid/agent-core/venv and installs the running CLI version into it.
- Writes/updates the systemd unit and enables the service.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from importlib import resources
from importlib.metadata import version as pkg_version
from pathlib import Path
from textwrap import dedent


# =========================
# Contract constants
# =========================
SERVICE_NAME = "lucid-agent-core"
SYSTEM_USER = "lucid"

ENV_DIR = Path("/etc/lucid")
ENV_PATH = ENV_DIR / "agent-core.env"

OPT_DIR = Path("/opt/lucid/agent-core")
VENV_DIR = OPT_DIR / "venv"

VAR_LIB = Path("/var/lib/lucid")
VAR_LOG = Path("/var/log/lucid")

UNIT_PATH = Path("/etc/systemd/system/lucid-agent-core.service")

PYTHON_311 = Path("/usr/bin/python3.11")

GITHUB_REPO = "LucidLabPlatform/lucid-agent-core"


# =========================
# Helpers
# =========================
def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("install-service must be run as root (use sudo).")


def _require_systemd() -> None:
    if shutil.which("systemctl") is None:
        raise SystemExit("systemctl not found. This host does not appear to run systemd.")


def _require_python311() -> None:
    if not PYTHON_311.exists():
        raise SystemExit(
            "Python 3.11 not found at /usr/bin/python3.11.\n"
            "Install it first:\n"
            "  sudo apt update && sudo apt install -y python3.11 python3.11-venv"
        )


def _ensure_user() -> None:
    res = subprocess.run(["id", "-u", SYSTEM_USER], capture_output=True)
    if res.returncode == 0:
        return

    if shutil.which("useradd") is None:
        raise SystemExit("useradd not found; cannot create system user.")

    _run(
        [
            "useradd",
            "--system",
            "--no-create-home",
            "--shell",
            "/usr/sbin/nologin",
            SYSTEM_USER,
        ]
    )


def _ensure_dirs() -> None:
    for p in (ENV_DIR, OPT_DIR, VAR_LIB, VAR_LOG):
        p.mkdir(parents=True, exist_ok=True)

    # Only chown runtime dirs
    _run(["chown", "-R", f"{SYSTEM_USER}:{SYSTEM_USER}", str(VAR_LIB), str(VAR_LOG)])


def _read_env_example_from_package() -> str:
    """
    Read env.example packaged inside lucid_agent_core.
    The file must exist at: src/lucid_agent_core/env.example
    """
    try:
        # Python 3.9+ API. Works for wheels and editable installs.
        env_example = resources.files("lucid_agent_core").joinpath("env.example")
        return env_example.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(
            "env.example not found inside the installed package.\n"
            "Fix: move env.example to src/lucid_agent_core/env.example and ensure it is packaged."
        )
    except Exception as e:
        raise SystemExit(f"Failed to load env.example from package resources: {e}")


def _ensure_env_file() -> None:
    """
    Create /etc/lucid/agent-core.env by copying env.example from the package.
    Never overwrite if it already exists.
    """
    if ENV_PATH.exists():
        return

    content = _read_env_example_from_package()
    ENV_PATH.write_text(content, encoding="utf-8")
    _run(["chmod", "600", str(ENV_PATH)])


def _ensure_venv() -> None:
    if not (VENV_DIR / "bin" / "python").exists():
        _run([str(PYTHON_311), "-m", "venv", str(VENV_DIR)])

    _run([str(VENV_DIR / "bin" / "pip"), "install", "--upgrade", "pip"])


def _current_version() -> str:
    return pkg_version("lucid-agent-core")


def _wheel_filename(version: str) -> str:
    # Your GitHub release uses underscore naming
    return f"lucid_agent_core-{version}-py3-none-any.whl"


def _release_wheel_url(version: str) -> str:
    tag = f"v{version}"
    return f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/{_wheel_filename(version)}"


def _install_wheel_into_venv(wheel_url: str) -> None:
    pip = str(VENV_DIR / "bin" / "pip")
    _run([pip, "install", "--upgrade", wheel_url])


def _write_unit_file() -> None:
    unit = dedent(
        f"""\
        [Unit]
        Description=LUCID Agent Core
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        User={SYSTEM_USER}
        Group={SYSTEM_USER}
        EnvironmentFile={ENV_PATH}
        ExecStart={VENV_DIR}/bin/lucid-agent-core
        WorkingDirectory={VAR_LIB}
        Restart=always
        RestartSec=2

        NoNewPrivileges=true
        PrivateTmp=true
        ProtectSystem=strict
        ProtectHome=true
        ReadWritePaths={VAR_LIB} {VAR_LOG}

        [Install]
        WantedBy=multi-user.target
        """
    )

    # Unit file is code; overwrite is OK. Avoid rewriting if unchanged.
    if UNIT_PATH.exists() and UNIT_PATH.read_text(encoding="utf-8") == unit:
        return

    UNIT_PATH.write_text(unit, encoding="utf-8")


def _enable_and_start() -> None:
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", "--now", SERVICE_NAME])


# =========================
# Public API
# =========================
def install_service() -> None:
    """
    One-command privileged install:
      - validates root, systemd, python3.11
      - creates system user + dirs
      - copies env.example -> /etc/lucid/agent-core.env (once)
      - creates venv under /opt
      - installs same version wheel into venv from GitHub Releases
      - writes systemd unit
      - enables + starts service
    """
    _require_root()
    _require_systemd()
    _require_python311()

    _ensure_user()
    _ensure_dirs()
    _ensure_env_file()
    _ensure_venv()

    v = _current_version()
    wheel_url = _release_wheel_url(v)
    _install_wheel_into_venv(wheel_url)

    _write_unit_file()
    _enable_and_start()

    print(f"Installed and started: {SERVICE_NAME}")
    print(f"Edit config: {ENV_PATH}")
    print(f"Status: systemctl status {SERVICE_NAME} --no-pager")
    print(f"Logs: journalctl -u {SERVICE_NAME} -f")
