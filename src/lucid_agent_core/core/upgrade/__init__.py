"""Upgrade subpackage — install, upgrade, and uninstall components and agent core."""

from lucid_agent_core.core.upgrade.component_installer import handle_install_component
from lucid_agent_core.core.upgrade.component_upgrader import handle_component_upgrade
from lucid_agent_core.core.upgrade.component_uninstaller import handle_uninstall_component
from lucid_agent_core.core.upgrade.core_upgrader import handle_core_upgrade

__all__ = [
    "handle_install_component",
    "handle_component_upgrade",
    "handle_uninstall_component",
    "handle_core_upgrade",
]
