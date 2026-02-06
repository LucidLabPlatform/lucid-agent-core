# lucid_agent_core/components/registry.py

from __future__ import annotations
import json
from pathlib import Path

REGISTRY_PATH = Path("/var/lib/lucid/components.json")


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {}
    with REGISTRY_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)
