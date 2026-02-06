"""
Agent Core Configuration

Single source for agent runtime configuration. All values are read from
environment variables. .env files are loaded automatically so you don't need
to export variables. Set them once per machine in a standard location.
"""

import os
import sys
from importlib.metadata import PackageNotFoundError, version as _pkg_version

_DEFAULTS = {"AGENT_HEARTBEAT": "30"}


def _config_dirs():
    """Yield paths to search for .env (first = lowest priority, later overrides)."""
    # 1) User config dir: set once per machine, works from any cwd
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    yield os.path.join(base, "lucid-agent-core", ".env")
    # 2) Current directory (e.g. project .env overrides)
    yield ".env"

# local | test — selects run context; used by Makefile and optionally by app
LUCID_MODE = os.getenv("LUCID_MODE", "local")

# Populated by load_config(); do not use before calling load_config()
MQTT_HOST = None
MQTT_PORT = None
AGENT_USERNAME = None
AGENT_PASSWORD = None
AGENT_VERSION = None
AGENT_HEARTBEAT = None


def get_required_env(key):
    """Get required environment variable or exit"""
    value = os.getenv(key)
    if value is None:
        print(f"ERROR: Required environment variable '{key}' is not set")
        sys.exit(1)
    return value


def get_package_version():
    """Get the installed package version (authoritative)."""
    try:
        return _pkg_version("lucid-agent-core")
    except PackageNotFoundError:
        print("ERROR: Could not determine lucid-agent-core version from package metadata")
        sys.exit(1)


def load_config():
    """Load config from .env (if present) and environment. Call before using MQTT_* etc."""
    global MQTT_HOST, MQTT_PORT, AGENT_USERNAME, AGENT_PASSWORD, AGENT_VERSION, AGENT_HEARTBEAT

    from dotenv import load_dotenv
    for path in _config_dirs():
        if os.path.isfile(path):
            load_dotenv(path)
    load_dotenv()  # cwd .env last so it overrides (e.g. when in project dir)

    MQTT_HOST = get_required_env("MQTT_HOST")
    MQTT_PORT = int(get_required_env("MQTT_PORT"))
    AGENT_USERNAME = get_required_env("AGENT_USERNAME")
    AGENT_PASSWORD = get_required_env("AGENT_PASSWORD")
    AGENT_VERSION = get_package_version()
    AGENT_HEARTBEAT = int(os.getenv("AGENT_HEARTBEAT", _DEFAULTS["AGENT_HEARTBEAT"]))
