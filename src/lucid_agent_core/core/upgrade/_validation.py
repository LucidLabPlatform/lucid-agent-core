"""
Shared validation utilities for upgrade/install operations.

Provides ValidationError, regex constants, best-effort payload extractors,
and a UTC timestamp helper used across all installer/upgrader modules.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

_COMPONENT_ID_RE = re.compile(r"^[a-z0-9_]+$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_GH_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class ValidationError(ValueError):
    """Raised when an install/upgrade payload fails validation."""


def utc_now() -> str:
    """Return current UTC time as an ISO8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_request_id_best_effort(raw_payload: str) -> str:
    """Extract request_id from a raw JSON payload, or return empty string."""
    try:
        obj = json.loads(raw_payload)
        if isinstance(obj, dict) and isinstance(obj.get("request_id"), str):
            return obj["request_id"]
    except Exception:
        pass
    return ""


def extract_component_id_best_effort(raw_payload: str) -> str:
    """Extract component_id from a raw JSON payload, or return empty string."""
    try:
        obj = json.loads(raw_payload)
        if isinstance(obj, dict) and isinstance(obj.get("component_id"), str):
            return obj["component_id"]
    except Exception:
        pass
    return ""


def extract_version_best_effort(raw_payload: str) -> str:
    """Extract version from a raw JSON payload's source field, or return empty string."""
    try:
        obj = json.loads(raw_payload)
        if isinstance(obj, dict):
            source = obj.get("source", {})
            if isinstance(source, dict) and isinstance(source.get("version"), str):
                return source["version"]
    except Exception:
        pass
    return ""
