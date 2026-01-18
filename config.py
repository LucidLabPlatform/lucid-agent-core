"""
Agent Core Configuration
Minimal config for Step 1.2 - device identity and broker credentials only
All values are required via environment variables
"""

import os
import sys
import uuid

def get_required_env(key):
    """Get required environment variable or exit"""
    value = os.getenv(key)
    if value is None:
        print(f"ERROR: Required environment variable '{key}' is not set")
        sys.exit(1)
    return value

# Device identity - unique per agent instance (random UUID)
DEVICE_ID = str(uuid.uuid4())

# MQTT Broker configuration
HOST = get_required_env("HOST")
PORT = int(get_required_env("PORT"))
USERNAME = get_required_env("USERNAME")
PASSWORD = get_required_env("PASSWORD")

# Agent version
VERSION = get_required_env("VERSION")
