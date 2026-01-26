"""
Agent Core Configuration

Single source for agent runtime configuration. All values are read from
environment variables. Root .env (from env.example) and docker-compose
must list the same variables and keep defaults in sync with _DEFAULTS.
"""

import os
import sys
import uuid

_DEFAULTS = {"AGENT_HEARTBEAT": "30"}

# local | docker | test — selects run context; used by Makefile and optionally by app
LUCID_MODE = os.getenv("LUCID_MODE", "local")


def get_required_env(key):
    """Get required environment variable or exit"""
    value = os.getenv(key)
    if value is None:
        print(f"ERROR: Required environment variable '{key}' is not set")
        sys.exit(1)
    return value


# Device identity - unique per agent instance (random UUID)
DEVICE_ID = str(uuid.uuid4())

# MQTT Broker (required)
MQTT_HOST = get_required_env("MQTT_HOST")
MQTT_PORT = int(get_required_env("MQTT_PORT"))

# Agent login (required)
AGENT_USERNAME = get_required_env("AGENT_USERNAME")
AGENT_PASSWORD = get_required_env("AGENT_PASSWORD")

# Agent version (required)
AGENT_VERSION = get_required_env("AGENT_VERSION")

# Agent heartbeat (optional; default from _DEFAULTS)
AGENT_HEARTBEAT = int(os.getenv("AGENT_HEARTBEAT", _DEFAULTS["AGENT_HEARTBEAT"]))
