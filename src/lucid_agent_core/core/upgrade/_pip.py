"""
pip subprocess helpers for install, upgrade, and uninstall operations.

All functions run pip from the agent venv (via get_paths().pip_path) and
return (stdout, stderr) tuples, raising RuntimeError on non-zero exit codes.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)


def _pip_path() -> Path:
    """Return the pip executable path from the agent venv."""
    return get_paths().pip_path


def pip_install_wheel(
    wheel_path: Path, *, component_id: str
) -> tuple[Optional[str], Optional[str]]:
    """
    Install *wheel_path* via pip, optionally installing the [pi] extra for led_strip.

    Returns (stdout, stderr). Raises RuntimeError on failure.
    """
    pip = _pip_path()
    if not pip.exists():
        raise FileNotFoundError(f"pip executable not found: {pip}")

    completed = subprocess.run(
        [str(pip), "install", "--upgrade", str(wheel_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"pip install failed rc={completed.returncode}\n"
            f"stdout:\n{(completed.stdout or '').strip()}\n"
            f"stderr:\n{(completed.stderr or '').strip()}"
        )

    out_lines = [completed.stdout or ""]
    err_lines = [completed.stderr or ""]

    # Install [pi] extra for led_strip so the helper has rpi_ws281x in the same venv.
    if component_id == "led_strip":
        extra = subprocess.run(
            [str(pip), "install", "lucid-component-led-strip[pi]"],
            check=False,
            capture_output=True,
            text=True,
        )
        if extra.returncode != 0:
            logger.warning(
                "pip install lucid-component-led-strip[pi] failed (helper may lack rpi_ws281x): %s",
                (extra.stderr or extra.stdout or "").strip(),
            )
        else:
            out_lines.append(extra.stdout or "")
            err_lines.append(extra.stderr or "")

    return "\n".join(out_lines).strip() or None, "\n".join(err_lines).strip() or None


def pip_upgrade_wheel(wheel_path: Path) -> tuple[Optional[str], Optional[str]]:
    """
    Upgrade a package from *wheel_path* via pip.

    Returns (stdout, stderr). Raises RuntimeError on failure.
    """
    pip = _pip_path()
    if not pip.exists():
        raise FileNotFoundError(f"pip executable not found: {pip}")

    completed = subprocess.run(
        [str(pip), "install", "--upgrade", str(wheel_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"pip install failed rc={completed.returncode}\n"
            f"stdout:\n{(completed.stdout or '').strip()}\n"
            f"stderr:\n{(completed.stderr or '').strip()}"
        )
    return completed.stdout, completed.stderr


def pip_uninstall_dist(dist_name: str) -> tuple[Optional[str], Optional[str]]:
    """
    Uninstall distribution *dist_name* via pip.

    Returns (stdout, stderr). Raises RuntimeError on failure.
    """
    pip = _pip_path()
    if not pip.exists():
        raise FileNotFoundError(f"pip executable not found: {pip}")

    completed = subprocess.run(
        [str(pip), "uninstall", "-y", dist_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"pip uninstall failed rc={completed.returncode}\n"
            f"stdout:\n{(completed.stdout or '').strip()}\n"
            f"stderr:\n{(completed.stderr or '').strip()}"
        )
    return completed.stdout, completed.stderr
