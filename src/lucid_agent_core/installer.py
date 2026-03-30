"""
System installer for LUCID Agent Core (systemd + venv runtime).

Contract:
- Idempotent: safe to re-run.
- Defaults to user 'lucid' with home /home/lucid, but honors environment overrides.
- Creates <base>/agent-core.env from packaged env.example and never overwrites it.
- Creates <base>/venv and installs into it.
- Supports local wheel installation via --wheel or LUCID_AGENT_CORE_WHEEL env var.
- Falls back to GitHub release URL if no local wheel provided.
- Writes/updates the systemd unit and enables the service.
- All files under the configured base directory with proper permissions.
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
SYSTEM_USER = os.environ.get("LUCID_AGENT_SYSTEM_USER", "lucid")
SYSTEM_HOME = Path(os.environ.get("LUCID_AGENT_SYSTEM_HOME", f"/home/{SYSTEM_USER}"))

BASE_DIR = Path(os.environ.get("LUCID_AGENT_BASE_DIR", str(SYSTEM_HOME / "lucid-agent-core")))
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

    Creates the configured system user with:
    - Home directory: the configured SYSTEM_HOME
    - Shell: /bin/bash
    - Reuses an existing home directory when present
    - Falls back to pre-creating the home directory if useradd -m fails
    """
    home_dir = SYSTEM_HOME
    if home_dir.exists() and not home_dir.is_dir():
        raise RuntimeError(
            f"Cannot create user '{SYSTEM_USER}': home path exists and is not a directory: {home_dir}"
        )

    try:
        _run(["id", SYSTEM_USER])
        print(f"User '{SYSTEM_USER}' already exists")
        home_dir.mkdir(parents=True, exist_ok=True)
        _run(["chown", f"{SYSTEM_USER}:{SYSTEM_USER}", str(home_dir)])
        return
    except subprocess.CalledProcessError:
        print(f"Creating user '{SYSTEM_USER}'...")

    create_cmd = [
        "useradd",
        "-m",  # Create home directory
        "-d",
        str(home_dir),
        "-s",
        "/bin/bash",
        SYSTEM_USER,
    ]
    reuse_cmd = [
        "useradd",
        "-M",  # Reuse an existing home directory
        "-d",
        str(home_dir),
        "-s",
        "/bin/bash",
        SYSTEM_USER,
    ]

    if home_dir.exists():
        _run(reuse_cmd)
    else:
        try:
            _run(create_cmd)
        except subprocess.CalledProcessError:
            print(
                f"useradd -m could not create {home_dir}; "
                "creating the directory manually and retrying..."
            )
            home_dir.parent.mkdir(parents=True, exist_ok=True)
            home_dir.mkdir(parents=True, exist_ok=True)
            try:
                _run(reuse_cmd)
            except subprocess.CalledProcessError as retry_exc:
                raise RuntimeError(
                    f"Failed to create user '{SYSTEM_USER}' with home {home_dir}"
                ) from retry_exc

    _run(["chown", f"{SYSTEM_USER}:{SYSTEM_USER}", str(home_dir)])
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


def _ensure_pip_cache() -> None:
    """
    Ensure pip cache directory exists with correct ownership.
    """
    cache_dir = SYSTEM_HOME / ".cache" / "pip"
    cache_dir.mkdir(parents=True, exist_ok=True)
    _run(["chown", "-R", f"{SYSTEM_USER}:{SYSTEM_USER}", str(cache_dir.parent)])
    print(f"Ensured pip cache directory: {cache_dir}")


def _ensure_venv_permissions() -> None:
    """
    Ensure venv directory and all contents are owned by SYSTEM_USER.
    This is critical for pip upgrades to work correctly.
    """
    if VENV_DIR.exists():
        _run(["chown", "-R", f"{SYSTEM_USER}:{SYSTEM_USER}", str(VENV_DIR)])
        print(f"Fixed venv permissions: {VENV_DIR}")


def _create_venv() -> None:
    if VENV_DIR.exists():
        print(f"Virtual environment already exists: {VENV_DIR}")
        # Still ensure permissions are correct (important for upgrades)
        _ensure_venv_permissions()
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
    # Ensure permissions are correct before installing (critical for upgrades)
    _ensure_venv_permissions()
    _ensure_pip_cache()

    pip = VENV_DIR / "bin" / "pip"

    if not pip.exists():
        raise FileNotFoundError(f"pip not found in venv: {pip}")

    if wheel_path:
        # Install from local wheel
        if not wheel_path.exists():
            raise FileNotFoundError(f"Wheel file not found: {wheel_path}")

        print(f"Installing from local wheel: {wheel_path}")
        # Run pip as SYSTEM_USER to ensure correct ownership of installed files
        _run(["sudo", "-u", SYSTEM_USER, str(pip), "install", "--upgrade", str(wheel_path)])
    else:
        # Install from GitHub release
        version = pkg_version("lucid-agent-core")
        wheel_url = (
            f"https://github.com/LucidLabPlatform/lucid-agent-core/"
            f"releases/download/v{version}/"
            f"lucid_agent_core-{version}-py3-none-any.whl"
        )

        print(f"Installing from GitHub release: {wheel_url}")
        # Run pip as SYSTEM_USER to ensure correct ownership of installed files
        _run(["sudo", "-u", SYSTEM_USER, str(pip), "install", "--upgrade", wheel_url])

    # Fix ownership again after installation (in case any files were created as root)
    _ensure_venv_permissions()

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
        unit_template = resources.files("lucid_agent_core").joinpath(
            "systemd/lucid-agent-core.service"
        )

        with unit_template.open("r", encoding="utf-8") as f:
            content = f.read()

    except Exception as exc:
        raise RuntimeError(f"Failed to load packaged systemd unit: {exc}") from exc

    content = content.replace("User=lucid", f"User={SYSTEM_USER}")
    content = content.replace("Group=lucid", f"Group={SYSTEM_USER}")
    content = content.replace("/home/lucid/lucid-agent-core", str(BASE_DIR))
    content = content.replace(
        "Environment=PYTHONUNBUFFERED=1",
        (
            "Environment=PYTHONUNBUFFERED=1\n"
            f"Environment=LUCID_AGENT_BASE_DIR={BASE_DIR}"
        ),
    )

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

    print("\n" + "=" * 60)
    print(f"✓ {SERVICE_NAME} installed and enabled successfully!")
    print("=" * 60)
    print(f"Base directory: {BASE_DIR}")
    print(f"Configuration: {ENV_PATH}")
    print("\nNext steps:")
    print(f"1. Edit {ENV_PATH} with your MQTT credentials")
    print(f"2. Start the service: sudo systemctl start {SERVICE_NAME}")
    print(f"3. Check status: sudo systemctl status {SERVICE_NAME}")
    print("=" * 60)


def install_led_strip_helper() -> None:
    """
    Install and enable the LED strip helper daemon (run as root).

    Uses the agent venv's lucid-led-strip-helper-installer. The agent does not
    run sudo; run this once on the device after installing the led_strip
    component via MQTT. Example:
      sudo /home/lucid/lucid-agent-core/venv/bin/lucid-agent-core install-led-strip-helper
    """
    _ensure_root()

    installer_exe = VENV_DIR / "bin" / "lucid-led-strip-helper-installer"
    if not installer_exe.is_file():
        print(
            f"LED strip helper installer not found: {installer_exe}\n"
            "Install the led_strip component in the agent venv first (e.g. via MQTT "
            "cmd/components/install), then run this command again."
        )
        raise SystemExit(1)

    print(f"Running {installer_exe} --install-once ...")
    _run([str(installer_exe), "--install-once"])
    print("LED strip helper installed and started.")
