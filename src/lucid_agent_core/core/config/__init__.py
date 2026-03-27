"""
Config subpackage — persistent runtime configuration store.

Public API:
  ConfigStore       — load / save / get_cached / apply_set_*
  ConfigStoreError  — raised on I/O or validation failures
"""

from lucid_agent_core.core.config.store import ConfigStore, ConfigStoreError

__all__ = ["ConfigStore", "ConfigStoreError"]
