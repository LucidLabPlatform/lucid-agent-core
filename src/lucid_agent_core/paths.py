"""
Central path configuration for LUCID Agent Core.

All filesystem paths are derived from a single base directory under /home/lucid.
This module provides a single source of truth for all file and directory paths.

Path Structure:
    /home/lucid/lucid-agent-core/
    ├── venv/              (Python virtual environment)
    ├── data/              (Persistent data)
    │   ├── components_registry.json
    │   └── core_config.json
    ├── logs/              (Application logs)
    │   └── agent-core.log
    └── run/               (Runtime state: PID files, locks, etc.)

Usage:
    from lucid_agent_core.paths import get_paths

    paths = get_paths()
    registry_path = paths.registry_path
    pip_path = paths.pip_path
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True, slots=True)
class Paths:
    """
    Immutable container for all filesystem paths used by the agent.

    All paths are absolute and derived from base_dir.
    """

    base_dir: Path
    venv_dir: Path
    data_dir: Path
    registry_path: Path
    config_path: Path
    log_dir: Path
    runtime_dir: Path

    @property
    def pip_path(self) -> Path:
        """Path to pip executable in venv."""
        return self.venv_dir / "bin" / "pip"

    @property
    def python_path(self) -> Path:
        """Path to python executable in venv."""
        return self.venv_dir / "bin" / "python"

    @property
    def cli_path(self) -> Path:
        """Path to lucid-agent-core CLI executable in venv."""
        return self.venv_dir / "bin" / "lucid-agent-core"

    @property
    def registry_lock_path(self) -> Path:
        """Path to registry lock file."""
        return self.data_dir / "components_registry.json.lock"

    @property
    def config_lock_path(self) -> Path:
        """Path to config lock file."""
        return self.data_dir / "core_config.json.lock"

    @property
    def restart_sentinel_path(self) -> Path:
        """Path to restart request sentinel file."""
        return self.runtime_dir / "restart.requested"


def build_paths(base_dir: Optional[Path] = None) -> Paths:
    """
    Build Paths object from base directory.

    Args:
        base_dir: Base directory for all agent files.
                  Defaults to /home/lucid/lucid-agent-core.
                  Can be overridden via LUCID_AGENT_BASE_DIR env var for testing.

    Returns:
        Immutable Paths object with all filesystem paths.
    """
    if base_dir is None:
        # Allow override via environment variable (useful for testing)
        base_str = os.environ.get("LUCID_AGENT_BASE_DIR", "/home/lucid/lucid-agent-core")
        base_dir = Path(base_str)

    return Paths(
        base_dir=base_dir,
        venv_dir=base_dir / "venv",
        data_dir=base_dir / "data",
        registry_path=base_dir / "data" / "components_registry.json",
        config_path=base_dir / "data" / "core_config.json",
        log_dir=base_dir / "logs",
        runtime_dir=base_dir / "run",
    )


def ensure_dirs(paths: Paths) -> None:
    """
    Create all required directories if they don't exist.

    Creates directories with appropriate permissions:
    - base_dir: 0o755
    - data_dir: 0o750 (sensitive configuration)
    - log_dir: 0o750
    - runtime_dir: 0o750

    Args:
        paths: Paths object with directories to create.

    Raises:
        OSError: If directory creation fails due to permissions or other issues.
    """
    # Create directories
    for dir_path, mode in [
        (paths.base_dir, 0o755),
        (paths.venv_dir, 0o755),
        (paths.data_dir, 0o750),
        (paths.log_dir, 0o750),
        (paths.runtime_dir, 0o750),
    ]:
        dir_path.mkdir(parents=True, exist_ok=True)
        # Set permissions explicitly (mkdir may apply umask)
        dir_path.chmod(mode)


# Global instance (lazy-initialized)
_paths: Optional[Paths] = None


def get_paths() -> Paths:
    """
    Get the global Paths instance.

    Lazily initializes on first call using build_paths() defaults.
    Subsequent calls return the cached instance.

    Returns:
        Global Paths instance.
    """
    global _paths
    if _paths is None:
        _paths = build_paths()
    return _paths


def set_paths(paths: Paths) -> None:
    """
    Set the global Paths instance.

    Useful for testing or when paths need to be customized.

    Args:
        paths: Paths instance to set as global.
    """
    global _paths
    _paths = paths


def reset_paths() -> None:
    """
    Reset the global Paths instance.

    Forces get_paths() to rebuild from defaults on next call.
    Primarily useful for testing.
    """
    global _paths
    _paths = None
