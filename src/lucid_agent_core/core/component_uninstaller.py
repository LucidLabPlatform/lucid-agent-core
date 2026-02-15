"""
Component uninstaller for LUCID Agent Core.

Handles MQTT uninstall commands: validates payload, runs pip uninstall,
updates registry, and returns structured result.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lucid_agent_core.components.registry import load_registry, write_registry
from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)

_COMPONENT_ID_RE = re.compile(r"^[a-z0-9_]+$")


class ValidationError(ValueError):
    """Raised when uninstall payload validation fails."""


def _utc_now() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class UninstallResult:
    """Result of component uninstall operation."""

    request_id: str
    component_id: str
    ok: bool
    ts: str
    noop: bool = False
    error: Optional[str] = None
    pip_stdout: Optional[str] = None
    pip_stderr: Optional[str] = None
    restart_required: bool = False


def handle_uninstall_component(raw_payload: str) -> UninstallResult:
    """
    Validate payload, uninstall component, update registry, return result.

    Args:
        raw_payload: JSON string with {request_id, component_id, dist_name?}

    Returns:
        UninstallResult with operation outcome

    Flow:
        1. Parse and validate JSON
        2. Load registry
        3. If not found: return ok=True, noop=True (idempotent)
        4. STRICT: Extract dist_name from registry OR payload (migration support)
        5. Run pip uninstall
        6. Remove from registry atomically
        7. Return result with restart_required=True

    Migration support:
        For registries from pre-v1.0.0 without dist_name, caller can provide
        dist_name explicitly in payload to enable uninstall. This maintains
        strictness while allowing recovery.
    """
    ts = _utc_now()

    # Parse and validate
    try:
        req = _parse_and_validate(raw_payload)
    except ValidationError as exc:
        return UninstallResult(
            request_id=_extract_request_id_best_effort(raw_payload),
            component_id=_extract_component_id_best_effort(raw_payload),
            ok=False,
            ts=ts,
            error=f"validation_error: {exc}",
            restart_required=False,
        )

    request_id = req["request_id"]
    component_id = req["component_id"]
    payload_dist_name = req.get("dist_name")  # Optional migration field

    try:
        # Load registry
        registry = load_registry()
        existing = registry.get(component_id)

        # Idempotent: if not installed, return success
        if existing is None:
            logger.info("Component %s not installed, noop", component_id)
            return UninstallResult(
                request_id=request_id,
                component_id=component_id,
                ok=True,
                ts=ts,
                noop=True,
                restart_required=False,
            )

        # Extract dist_name: prefer registry, fallback to payload (migration)
        dist_name = existing.get("dist_name")
        if not dist_name and payload_dist_name:
            logger.warning(
                "Component %s registry missing dist_name, using payload value (migration)",
                component_id,
            )
            dist_name = payload_dist_name

        if not dist_name:
            logger.error("Component %s registry missing dist_name and none provided", component_id)
            return UninstallResult(
                request_id=request_id,
                component_id=component_id,
                ok=False,
                ts=ts,
                error=(
                    "registry missing dist_name for component; "
                    "provide dist_name in uninstall payload for migration"
                ),
                restart_required=False,
            )

        # Run pip uninstall
        pip_out, pip_err = _pip_uninstall(dist_name)

        # Remove from registry atomically
        del registry[component_id]
        write_registry(registry)

        logger.info("Uninstalled component %s (dist: %s)", component_id, dist_name)

        return UninstallResult(
            request_id=request_id,
            component_id=component_id,
            ok=True,
            ts=ts,
            noop=False,
            pip_stdout=pip_out,
            pip_stderr=pip_err,
            restart_required=True,  # Python modules removed, restart needed
        )

    except Exception as exc:
        logger.exception("Uninstall failed component=%s", component_id)
        return UninstallResult(
            request_id=request_id,
            component_id=component_id,
            ok=False,
            ts=ts,
            error=str(exc),
            restart_required=False,
        )


def _parse_and_validate(raw_payload: str) -> dict[str, str]:
    """
    Parse and validate uninstall payload.

    Args:
        raw_payload: JSON string

    Returns:
        Dict with request_id, component_id, and optional dist_name

    Raises:
        ValidationError: If payload is invalid
    """
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"payload must be valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object")

    # Required fields
    for key in ("request_id", "component_id"):
        if key not in payload:
            raise ValidationError(f"missing required key: {key}")

    request_id = payload["request_id"]
    component_id = payload["component_id"]

    if not isinstance(request_id, str) or not request_id:
        raise ValidationError("request_id must be a non-empty string")

    if not isinstance(component_id, str) or not _COMPONENT_ID_RE.fullmatch(component_id):
        raise ValidationError(f"component_id must match ^[a-z0-9_]+$: {component_id}")

    result = {"request_id": request_id, "component_id": component_id}

    # Optional dist_name for migration support
    if "dist_name" in payload:
        dist_name = payload["dist_name"]
        if not isinstance(dist_name, str) or not dist_name:
            raise ValidationError("dist_name must be a non-empty string if provided")
        result["dist_name"] = dist_name

    return result


def _pip_uninstall(dist_name: str) -> tuple[Optional[str], Optional[str]]:
    """
    Run pip uninstall for a distribution.

    Args:
        dist_name: Python distribution name to uninstall

    Returns:
        Tuple of (stdout, stderr)

    Raises:
        RuntimeError: If pip uninstall fails
    """
    paths = get_paths()
    pip_path = paths.pip_path
    
    if not pip_path.exists():
        raise FileNotFoundError(f"pip executable not found: {pip_path}")

    completed = subprocess.run(
        [str(pip_path), "uninstall", "-y", dist_name],
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


def _extract_request_id_best_effort(raw_payload: str) -> str:
    """Extract request_id from payload, or return empty string."""
    try:
        obj = json.loads(raw_payload)
        if isinstance(obj, dict) and isinstance(obj.get("request_id"), str):
            return obj["request_id"]
    except Exception:
        pass
    return ""


def _extract_component_id_best_effort(raw_payload: str) -> str:
    """Extract component_id from payload, or return empty string."""
    try:
        obj = json.loads(raw_payload)
        if isinstance(obj, dict) and isinstance(obj.get("component_id"), str):
            return obj["component_id"]
    except Exception:
        pass
    return ""
