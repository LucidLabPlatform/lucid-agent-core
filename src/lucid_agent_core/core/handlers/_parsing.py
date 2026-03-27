"""
MQTT payload parsing utilities for command handlers.

Pure functions with no side effects — safe to import anywhere.
"""

from __future__ import annotations

import json


def request_id(payload_str: str) -> str:
    """Extract request_id from a JSON payload string, or return empty string."""
    try:
        payload = json.loads(payload_str) if payload_str else {}
        return payload.get("request_id", "")
    except json.JSONDecodeError:
        return ""


def parse_payload(payload_str: str) -> dict:
    """Parse a JSON payload string into a dict, returning {} on any error."""
    try:
        return json.loads(payload_str) if payload_str else {}
    except json.JSONDecodeError:
        return {}
