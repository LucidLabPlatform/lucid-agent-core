"""
Agent Core self-upgrade handler.

Validates upgrade payload, downloads the core wheel from GitHub,
verifies SHA256, upgrades the venv via pip, and signals a restart.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lucid_agent_core.core.upgrade._download import DOWNLOAD_TIMEOUT_S, MAX_WHEEL_BYTES, download_wheel, verify_sha256
from lucid_agent_core.core.upgrade._github_release import fetch_release_wheel_sha256
from lucid_agent_core.core.upgrade._pip import pip_upgrade_wheel
from lucid_agent_core.core.upgrade._validation import (
    ValidationError,
    _SEMVER_RE,
    _SHA256_RE,
    utc_now,
)

# Matches: lucid-foo @ git+https://github.com/Owner/repo@v1.2.3
_LUCID_GIT_DEP_RE = re.compile(
    r"^(lucid-[\w-]+)\s*@\s*git\+https://github\.com/([^/]+)/([^@\s]+)@v([\d]+\.[\d]+\.[\d]+)",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

CORE_GITHUB_OWNER = "LucidLabPlatform"
CORE_GITHUB_REPO = "lucid-agent-core"
CORE_PACKAGE_NAME = "lucid_agent_core"


@dataclass(frozen=True, slots=True)
class UpgradeRequest:
    request_id: str
    release_type: str
    version: str
    sha256: str

    def validate(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValidationError("request_id must be a non-empty string")
        if self.release_type != "github_release":
            raise ValidationError('release_type must be "github_release"')
        if not isinstance(self.version, str) or not _SEMVER_RE.fullmatch(self.version):
            raise ValidationError("version must be semver like 1.2.3")
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise ValidationError("sha256 must be 64 hex chars")

    @property
    def wheel_filename(self) -> str:
        return f"{CORE_PACKAGE_NAME}-{self.version}-py3-none-any.whl"

    @property
    def wheel_url(self) -> str:
        if self.release_type != "github_release":
            raise ValidationError(f"unsupported release_type: {self.release_type}")
        tag = f"v{self.version}"
        return (
            f"https://github.com/{CORE_GITHUB_OWNER}/{CORE_GITHUB_REPO}"
            f"/releases/download/{tag}/{self.wheel_filename}"
        )


@dataclass(frozen=True, slots=True)
class UpgradeResult:
    request_id: str
    version: str
    ok: bool
    ts: str
    wheel_url: Optional[str] = None
    sha256: Optional[str] = None
    error: Optional[str] = None
    pip_stdout: Optional[str] = None
    pip_stderr: Optional[str] = None
    restart_required: bool = True


def handle_core_upgrade(raw_payload: str) -> UpgradeResult:
    """
    Validate payload, download core wheel, verify SHA256, upgrade venv, return result.
    Always requires restart.
    """
    ts = utc_now()

    try:
        req = _parse_and_validate(raw_payload)
    except ValidationError as exc:
        logger.warning("Core upgrade validation failed: %s", exc)
        try:
            obj = json.loads(raw_payload) if raw_payload else {}
        except json.JSONDecodeError:
            obj = {}
        return UpgradeResult(
            request_id=obj.get("request_id", ""),
            version=obj.get("version", ""),
            ok=False,
            ts=ts,
            error=f"validation_error: {exc}",
            restart_required=True,
        )

    logger.info("Core upgrade started: version=%s request_id=%s", req.version, req.request_id)
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
                user_agent="lucid-agent-core/upgrader",
            )
            _size = wheel_path.stat().st_size if wheel_path.exists() else -1
            logger.debug("Wheel downloaded: %d bytes", _size)
            logger.debug("Verifying SHA256: expected=%s…", req.sha256[:16])
            verify_sha256(wheel_path, expected=req.sha256)
            logger.debug("SHA256 verified OK")
            _auto_upgrade_lucid_deps(wheel_path)
            logger.info("Running pip upgrade: wheel=%s", req.wheel_filename)
            pip_out, pip_err = pip_upgrade_wheel(wheel_path)
            logger.debug("pip upgrade stdout: %s", (pip_out or "(empty)")[:500])
            logger.debug("pip upgrade stderr: %s", (pip_err or "(empty)")[:500])

        logger.info("Core upgrade complete: version=%s", req.version)
        return UpgradeResult(
            request_id=req.request_id,
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
        logger.exception("Core upgrade failed")
        return UpgradeResult(
            request_id=req.request_id,
            version=req.version,
            ok=False,
            ts=ts,
            wheel_url=req.wheel_url,
            sha256=req.sha256.lower(),
            error=str(exc),
            restart_required=False,
        )


def _read_lucid_git_deps(wheel_path: Path) -> list[tuple[str, str, str, str]]:
    """
    Open *wheel_path* as a zip, parse METADATA Requires-Dist lines, and return
    [(pkg_name, owner, repo, version)] for every lucid-* dep pinned via a git URL.
    """
    deps: list[tuple[str, str, str, str]] = []
    try:
        with zipfile.ZipFile(wheel_path) as zf:
            metadata_names = [n for n in zf.namelist() if n.endswith("/METADATA")]
            if not metadata_names:
                return deps
            metadata = zf.read(metadata_names[0]).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Could not read wheel METADATA for dep auto-upgrade: %s", exc)
        return deps

    for line in metadata.splitlines():
        if not line.startswith("Requires-Dist:"):
            continue
        value = line[len("Requires-Dist:"):].strip()
        m = _LUCID_GIT_DEP_RE.match(value)
        if m:
            deps.append((m.group(1), m.group(2), m.group(3), m.group(4)))
    return deps


def _auto_upgrade_lucid_deps(wheel_path: Path) -> None:
    """
    Read lucid-* git deps from *wheel_path* METADATA and upgrade each one
    automatically before the core wheel is installed.
    """
    deps = _read_lucid_git_deps(wheel_path)
    if not deps:
        logger.debug("No lucid git deps found in wheel METADATA")
        return

    for pkg, owner, repo, version in deps:
        tag = f"v{version}"
        logger.info("Auto-upgrading dep %s to %s", pkg, version)
        try:
            dep_filename, dep_sha256 = fetch_release_wheel_sha256(owner, repo, tag)
            dep_url = f"https://github.com/{owner}/{repo}/releases/download/{tag}/{dep_filename}"
            with tempfile.TemporaryDirectory() as dep_tmp:
                dep_path = Path(dep_tmp) / dep_filename
                download_wheel(
                    dep_url,
                    dep_path,
                    timeout_s=DOWNLOAD_TIMEOUT_S,
                    max_bytes=MAX_WHEEL_BYTES,
                    user_agent="lucid-agent-core/dep-auto-upgrader",
                )
                verify_sha256(dep_path, expected=dep_sha256)
                pip_upgrade_wheel(dep_path)
            logger.info("Dep %s upgraded to %s", pkg, version)
        except Exception as exc:
            logger.warning("Failed to auto-upgrade dep %s to %s: %s", pkg, version, exc)


def _parse_and_validate(raw_payload: str) -> UpgradeRequest:
    try:
        obj = json.loads(raw_payload) if raw_payload else {}
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise ValidationError("payload must be a dict")

    req = UpgradeRequest(
        request_id=obj.get("request_id", ""),
        release_type=obj.get("release_type", "github_release"),
        version=obj.get("version", ""),
        sha256=obj.get("sha256", ""),
    )
    req.validate()
    return req
