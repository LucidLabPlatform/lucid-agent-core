"""
Component uninstaller — handles MQTT uninstall commands.

Validates payload, runs pip uninstall, removes the component from the registry,
and returns a structured result.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from lucid_agent_core.components.registry import load_registry, write_registry
from lucid_agent_core.core.upgrade._pip import pip_uninstall_dist
from lucid_agent_core.core.upgrade._validation import (
    ValidationError,
    _COMPONENT_ID_RE,
    extract_component_id_best_effort,
    extract_request_id_best_effort,
    utc_now,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UninstallResult:
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
    Validate payload, uninstall component via pip, remove from registry, return result.
    Idempotent: returns ok=True, noop=True if the component is not installed.
    """
    ts = utc_now()

    try:
        req = _parse_and_validate(raw_payload)
    except ValidationError as exc:
        return UninstallResult(
            request_id=extract_request_id_best_effort(raw_payload),
            component_id=extract_component_id_best_effort(raw_payload),
            ok=False,
            ts=ts,
            error=f"validation_error: {exc}",
            restart_required=False,
        )

    request_id = req["request_id"]
    component_id = req["component_id"]

    try:
        registry = load_registry()
        existing = registry.get(component_id)

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

        dist_name = existing.get("dist_name")
        if not dist_name:
            logger.error("Component %s registry missing dist_name", component_id)
            return UninstallResult(
                request_id=request_id,
                component_id=component_id,
                ok=False,
                ts=ts,
                error="registry missing dist_name; reinstall the component",
                restart_required=False,
            )

        pip_out, pip_err = pip_uninstall_dist(dist_name)

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
            restart_required=True,
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
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"payload must be valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object")

    for key in ("request_id", "component_id"):
        if key not in payload:
            raise ValidationError(f"missing required key: {key}")

    request_id = payload["request_id"]
    component_id = payload["component_id"]

    if not isinstance(request_id, str) or not request_id:
        raise ValidationError("request_id must be a non-empty string")
    if not isinstance(component_id, str) or not _COMPONENT_ID_RE.fullmatch(component_id):
        raise ValidationError(f"component_id must match ^[a-z0-9_]+$: {component_id}")

    return {"request_id": request_id, "component_id": component_id}
