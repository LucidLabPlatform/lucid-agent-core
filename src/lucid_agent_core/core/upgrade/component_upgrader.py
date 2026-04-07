"""
Component upgrade handler.

Validates upgrade payload, downloads wheel from GitHub, verifies SHA256,
upgrades via pip, updates the registry, and signals a restart.
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lucid_agent_core.components.registry import load_registry, write_registry
from lucid_agent_core.core.upgrade._download import DOWNLOAD_TIMEOUT_S, MAX_WHEEL_BYTES, download_wheel, verify_sha256
from lucid_agent_core.core.upgrade._pip import pip_upgrade_wheel
from lucid_agent_core.core.upgrade._validation import (
    ValidationError,
    _COMPONENT_ID_RE,
    _SEMVER_RE,
    _SHA256_RE,
    utc_now,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ComponentUpgradeRequest:
    request_id: str
    component_id: str
    release_type: str
    version: str
    sha256: str
    owner: str
    repo: str
    dist_name: str

    def validate(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValidationError("request_id must be a non-empty string")
        if not isinstance(self.component_id, str) or not _COMPONENT_ID_RE.fullmatch(
            self.component_id
        ):
            raise ValidationError(f"component_id must match ^[a-z0-9_]+$: {self.component_id}")
        if self.release_type != "github_release":
            raise ValidationError('release_type must be "github_release"')
        if not isinstance(self.version, str) or not _SEMVER_RE.fullmatch(self.version):
            raise ValidationError("version must be semver like 1.2.3")
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise ValidationError("sha256 must be 64 hex chars")
        if not isinstance(self.owner, str) or not self.owner:
            raise ValidationError("owner must be a non-empty string")
        if not isinstance(self.repo, str) or not self.repo:
            raise ValidationError("repo must be a non-empty string")
        if not isinstance(self.dist_name, str) or not self.dist_name:
            raise ValidationError("dist_name must be a non-empty string")

    @property
    def wheel_filename(self) -> str:
        wheel_name = self.dist_name.replace("-", "_")
        return f"{wheel_name}-{self.version}-py3-none-any.whl"

    @property
    def wheel_url(self) -> str:
        if self.release_type != "github_release":
            raise ValidationError(f"unsupported release_type: {self.release_type}")
        tag = f"v{self.version}"
        return f"https://github.com/{self.owner}/{self.repo}/releases/download/{tag}/{self.wheel_filename}"


@dataclass(frozen=True, slots=True)
class ComponentUpgradeResult:
    request_id: str
    component_id: str
    version: str
    ok: bool
    ts: str
    wheel_url: Optional[str] = None
    sha256: Optional[str] = None
    error: Optional[str] = None
    pip_stdout: Optional[str] = None
    pip_stderr: Optional[str] = None
    restart_required: bool = True


def handle_component_upgrade(raw_payload: str) -> ComponentUpgradeResult:
    """
    Validate payload, download wheel, verify SHA256, upgrade venv, update registry, return result.
    Always requires restart.
    """
    ts = utc_now()

    try:
        req = _parse_and_validate(raw_payload)
    except ValidationError as exc:
        try:
            payload_obj = json.loads(raw_payload) if raw_payload else {}
        except json.JSONDecodeError:
            payload_obj = {}
        logger.warning(
            "Component upgrade validation failed component=%s: %s",
            payload_obj.get("component_id", "?"),
            exc,
        )
        return ComponentUpgradeResult(
            request_id=payload_obj.get("request_id", ""),
            component_id=payload_obj.get("component_id", ""),
            version=payload_obj.get("version", ""),
            ok=False,
            ts=ts,
            error=f"validation_error: {exc}",
            restart_required=False,
        )

    logger.info(
        "Component upgrade started: component=%s version=%s request_id=%s",
        req.component_id,
        req.version,
        req.request_id,
    )
    logger.debug("Wheel URL: %s", req.wheel_url)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            wheel_path = Path(tmp) / req.wheel_filename
            logger.info("Downloading wheel: %s", req.wheel_url)
            download_wheel(
                req.wheel_url,
                wheel_path,
                timeout_s=DOWNLOAD_TIMEOUT_S,
                max_bytes=MAX_WHEEL_BYTES,
                user_agent="lucid-agent-core/component-upgrader",
            )
            _size = wheel_path.stat().st_size if wheel_path.exists() else -1
            logger.debug("Wheel downloaded: %d bytes", _size)
            logger.debug("Verifying SHA256: expected=%s…", req.sha256[:16])
            verify_sha256(wheel_path, expected=req.sha256)
            logger.debug("SHA256 verified OK")
            logger.info(
                "Running pip upgrade: component=%s wheel=%s", req.component_id, req.wheel_filename
            )
            pip_out, pip_err = pip_upgrade_wheel(wheel_path)
            logger.debug("pip upgrade stdout: %s", (pip_out or "(empty)")[:500])
            logger.debug("pip upgrade stderr: %s", (pip_err or "(empty)")[:500])

        # Snapshot the old registry entry before mutating so we can roll back
        # if the registry write fails after pip has already installed the new wheel.
        registry = load_registry()
        old_entry = dict(registry.get(req.component_id) or {})

        try:
            entry = registry.setdefault(req.component_id, {})
            entry["version"] = req.version
            entry["wheel_url"] = req.wheel_url
            entry["sha256"] = req.sha256.lower()
            write_registry(registry)
        except Exception as post_exc:
            logger.error(
                "Post-upgrade registry write failed for component=%s (%s) — attempting rollback",
                req.component_id,
                post_exc,
            )
            old_wheel_url = old_entry.get("wheel_url", "")
            old_version = old_entry.get("version", "")
            old_dist = (old_entry.get("dist_name") or req.dist_name).replace("-", "_")
            if old_wheel_url and old_version:
                try:
                    with tempfile.TemporaryDirectory() as rollback_tmp:
                        old_wheel_path = (
                            Path(rollback_tmp) / f"{old_dist}-{old_version}-py3-none-any.whl"
                        )
                        download_wheel(
                            old_wheel_url,
                            old_wheel_path,
                            timeout_s=DOWNLOAD_TIMEOUT_S,
                            max_bytes=MAX_WHEEL_BYTES,
                            user_agent="lucid-agent-core/component-upgrader-rollback",
                        )
                        pip_upgrade_wheel(old_wheel_path)
                        logger.info(
                            "Rollback complete: reinstalled component=%s version=%s",
                            req.component_id,
                            old_version,
                        )
                except Exception as rollback_exc:
                    logger.error(
                        "Rollback failed for component=%s: %s — system may be in inconsistent state",
                        req.component_id,
                        rollback_exc,
                    )
            else:
                logger.error(
                    "No previous wheel_url/version for component=%s — system may be in inconsistent state",
                    req.component_id,
                )
            raise post_exc

        logger.info("Registry updated: component=%s version=%s", req.component_id, req.version)
        logger.info(
            "Component upgrade complete: component=%s version=%s", req.component_id, req.version
        )

        return ComponentUpgradeResult(
            request_id=req.request_id,
            component_id=req.component_id,
            version=req.version,
            ok=True,
            ts=ts,
            wheel_url=req.wheel_url,
            sha256=req.sha256.lower(),
            pip_stdout=pip_out,
            pip_stderr=pip_err,
            restart_required=True,
        )
    except Exception as exc:
        logger.exception("Component upgrade failed")
        return ComponentUpgradeResult(
            request_id=req.request_id,
            component_id=req.component_id,
            version=req.version,
            ok=False,
            ts=ts,
            wheel_url=req.wheel_url,
            sha256=req.sha256.lower(),
            error=str(exc),
            restart_required=False,
        )


def _parse_and_validate(raw_payload: str) -> ComponentUpgradeRequest:
    """Parse and validate upgrade payload, enriching with registry data."""
    try:
        obj = json.loads(raw_payload) if raw_payload else {}
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise ValidationError("payload must be a dict")

    component_id = obj.get("component_id", "")
    registry = load_registry()
    if component_id not in registry:
        raise ValidationError(f"component not found in registry: {component_id}")

    component_info = registry[component_id]
    repo_str = component_info.get("repo", "")
    if not repo_str or "/" not in repo_str:
        raise ValidationError(
            f"invalid repo format in registry for {component_id}: {repo_str}"
        )

    owner, repo = repo_str.split("/", 1)
    dist_name = component_info.get("dist_name", "")
    if not dist_name:
        raise ValidationError(f"dist_name not found in registry for {component_id}")

    req = ComponentUpgradeRequest(
        request_id=obj.get("request_id", ""),
        component_id=component_id,
        release_type=obj.get("release_type", "github_release"),
        version=obj.get("version", ""),
        sha256=obj.get("sha256", ""),
        owner=owner,
        repo=repo,
        dist_name=dist_name,
    )
    req.validate()
    return req
