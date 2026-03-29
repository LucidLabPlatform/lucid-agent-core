"""
Component installer — handles MQTT install commands.

Validates payload, fetches the release asset from GitHub, downloads the wheel,
verifies SHA256, runs pip install, discovers the entrypoint, and updates the registry.
"""

from __future__ import annotations

import importlib
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from lucid_agent_core.components.registry import is_same_install, load_registry, write_registry
from lucid_agent_core.core.upgrade._github_release import build_wheel_url, fetch_release_asset
from lucid_agent_core.core.upgrade._download import DOWNLOAD_TIMEOUT_S, MAX_WHEEL_BYTES, download_wheel, verify_sha256
from lucid_agent_core.core.upgrade._pip import pip_install_wheel, pip_uninstall_dist
from lucid_agent_core.core.upgrade._validation import (
    ValidationError,
    _GH_NAME_RE,
    _COMPONENT_ID_RE,
    _SEMVER_RE,
    _SHA256_RE,
    extract_component_id_best_effort,
    extract_request_id_best_effort,
    extract_version_best_effort,
    utc_now,
)

try:
    from importlib.metadata import version as _pkg_version

    _AGENT_VERSION = _pkg_version("lucid-agent-core")
except Exception:
    _AGENT_VERSION = "0.0.0"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GithubReleaseSource:
    type: Literal["github_release"]
    owner: str
    repo: str
    version: str
    sha256: str

    def validate(self) -> None:
        if self.type != "github_release":
            raise ValidationError('source.type must be "github_release"')
        if not _GH_NAME_RE.fullmatch(self.owner):
            raise ValidationError("source.owner is invalid")
        if not _GH_NAME_RE.fullmatch(self.repo):
            raise ValidationError("source.repo is invalid")
        if not isinstance(self.version, str) or not _SEMVER_RE.fullmatch(self.version):
            raise ValidationError("source.version must be semver like 1.2.3")
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise ValidationError("source.sha256 must be 64 hex chars")


@dataclass(frozen=True, slots=True)
class InstallRequest:
    request_id: str
    component_id: str
    source: GithubReleaseSource

    def validate(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValidationError("request_id must be a non-empty string")
        if not isinstance(self.component_id, str) or not _COMPONENT_ID_RE.fullmatch(
            self.component_id
        ):
            raise ValidationError(f"component_id must match ^[a-z0-9_]+$: {self.component_id}")
        self.source.validate()


@dataclass(frozen=True, slots=True)
class InstallResult:
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
    restart_required: bool = False


def handle_install_component(raw_payload: str) -> InstallResult:
    """
    Validates payload, fetches release asset from GitHub API, downloads wheel,
    verifies integrity, installs, discovers entrypoint, updates registry, and
    returns a structured result.
    """
    ts = utc_now()

    try:
        req = _parse_and_validate(raw_payload)
    except ValidationError as exc:
        logger.warning(
            "Install validation failed component=%s: %s",
            extract_component_id_best_effort(raw_payload) or "?",
            exc,
        )
        return InstallResult(
            request_id=extract_request_id_best_effort(raw_payload),
            component_id=extract_component_id_best_effort(raw_payload),
            version=extract_version_best_effort(raw_payload),
            ok=False,
            ts=ts,
            error=f"validation_error: {exc}",
            restart_required=False,
        )

    logger.info(
        "Install started: component=%s version=%s request_id=%s",
        req.component_id,
        req.source.version,
        req.request_id,
    )
    tag = f"v{req.source.version}"
    wheel_url: Optional[str] = None

    try:
        registry = load_registry()
        existing = registry.get(req.component_id)
        existing_entrypoint = existing.get("entrypoint", "") if isinstance(existing, dict) else ""

        if is_same_install(
            existing,
            f"{req.source.owner}/{req.source.repo}",
            req.source.version,
            existing_entrypoint,
        ):
            logger.info(
                "Install skipped (already installed): component=%s version=%s",
                req.component_id,
                req.source.version,
            )
            return InstallResult(
                request_id=req.request_id,
                component_id=req.component_id,
                version=req.source.version,
                ok=True,
                ts=ts,
                wheel_url=existing.get("wheel_url") if isinstance(existing, dict) else None,
                sha256=req.source.sha256.lower(),
                restart_required=False,
            )

        logger.debug(
            "Fetching release asset from GitHub: %s/%s tag=%s",
            req.source.owner,
            req.source.repo,
            tag,
        )
        asset = fetch_release_asset(req.source.owner, req.source.repo, tag)
        logger.debug("GitHub asset resolved: %s", asset)
        wheel_url = build_wheel_url(req.source.owner, req.source.repo, tag, asset)

        with tempfile.TemporaryDirectory() as tmp:
            wheel_path = Path(tmp) / asset
            logger.info("Downloading wheel: %s", wheel_url)
            download_wheel(
                wheel_url,
                wheel_path,
                timeout_s=DOWNLOAD_TIMEOUT_S,
                max_bytes=MAX_WHEEL_BYTES,
                user_agent=f"lucid-agent-core/{_AGENT_VERSION}",
            )
            _size = wheel_path.stat().st_size if wheel_path.exists() else -1
            logger.debug("Wheel downloaded: %d bytes → %s", _size, wheel_path.name)
            logger.debug("Verifying SHA256: expected=%s…", req.source.sha256[:16])
            verify_sha256(wheel_path, expected=req.source.sha256)
            logger.debug("SHA256 verified OK")
            logger.info("Running pip install: component=%s wheel=%s", req.component_id, asset)
            pip_out, pip_err = pip_install_wheel(wheel_path, component_id=req.component_id)
            logger.debug("pip install stdout: %s", (pip_out or "(empty)")[:500])
            logger.debug("pip install stderr: %s", (pip_err or "(empty)")[:500])

        # dist_name is derived from the wheel filename — compute it before any
        # step that might fail so it's available for rollback.
        dist_name = _extract_dist_name_from_wheel(asset)

        try:
            entrypoint = _discover_entrypoint(req.component_id)
            logger.debug("Entrypoint discovered: %s", entrypoint)
            _verify_entrypoint(entrypoint)

            registry[req.component_id] = {
                "repo": f"{req.source.owner}/{req.source.repo}",
                "version": req.source.version,
                "wheel_url": wheel_url,
                "entrypoint": entrypoint,
                "sha256": req.source.sha256.lower(),
                "dist_name": dist_name,
                "enabled": True,
                "source": {
                    "type": req.source.type,
                    "owner": req.source.owner,
                    "repo": req.source.repo,
                    "tag": tag,
                    "asset": asset,
                },
                "installed_at": ts,
            }
            write_registry(registry)
        except Exception as post_exc:
            logger.error(
                "Post-install step failed for component=%s (%s) — attempting rollback",
                req.component_id,
                post_exc,
            )
            try:
                pip_uninstall_dist(dist_name)
                logger.info("Rollback complete: uninstalled %s", dist_name)
            except Exception as rollback_exc:
                logger.error(
                    "Rollback failed for %s: %s — system may be in inconsistent state",
                    dist_name,
                    rollback_exc,
                )
            raise

        logger.info(
            "Registry updated: component=%s version=%s entrypoint=%s",
            req.component_id,
            req.source.version,
            entrypoint,
        )
        logger.info(
            "Install complete: component=%s version=%s restart_required=True",
            req.component_id,
            req.source.version,
        )

        return InstallResult(
            request_id=req.request_id,
            component_id=req.component_id,
            version=req.source.version,
            ok=True,
            ts=ts,
            wheel_url=wheel_url,
            sha256=req.source.sha256.lower(),
            pip_stdout=pip_out,
            pip_stderr=pip_err,
            restart_required=True,
        )

    except Exception as exc:
        logger.exception(
            "Install failed component=%s version=%s", req.component_id, req.source.version
        )
        return InstallResult(
            request_id=req.request_id,
            component_id=req.component_id,
            version=req.source.version,
            ok=False,
            ts=ts,
            wheel_url=wheel_url,
            sha256=req.source.sha256.lower(),
            error=str(exc),
            restart_required=False,
        )


def _parse_and_validate(raw_payload: str) -> InstallRequest:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"payload must be valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object")

    for key in ("request_id", "component_id", "source"):
        if key not in payload:
            raise ValidationError(f"missing required key: {key}")

    source_obj = payload["source"]
    if not isinstance(source_obj, dict):
        raise ValidationError("source must be an object")

    source = GithubReleaseSource(
        type=source_obj.get("type"),
        owner=source_obj.get("owner"),
        repo=source_obj.get("repo"),
        version=source_obj.get("version"),
        sha256=source_obj.get("sha256"),
    )
    req = InstallRequest(
        request_id=payload["request_id"],
        component_id=payload["component_id"],
        source=source,
    )
    req.validate()
    return req


def _discover_entrypoint(component_id: str) -> str:
    """Discover component entrypoint via importlib.metadata entry_points after install."""
    from importlib.metadata import entry_points

    for ep in entry_points(group="lucid_components"):
        if ep.name == component_id:
            return ep.value
    raise ValidationError(
        f"no entry point for component_id={component_id!r} in group 'lucid_components'; "
        'ensure the wheel declares [project.entry-points."lucid_components"]'
    )


def _verify_entrypoint(entrypoint: str) -> None:
    module_name, class_name = entrypoint.split(":", 1)
    module = importlib.import_module(module_name)
    getattr(module, class_name)


def _extract_dist_name_from_wheel(wheel_filename: str) -> str:
    """
    Extract distribution name from wheel filename.
    Wheel format: {distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl
    """
    if wheel_filename.endswith(".whl"):
        wheel_filename = wheel_filename[:-4]
    parts = wheel_filename.split("-", 1)
    return parts[0].replace("_", "-")
