"""
Agent Core self-upgrade handler.

Downloads wheel from GitHub release, verifies SHA256, upgrades venv, restarts service.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_GH_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

MAX_WHEEL_BYTES = 200 * 1024 * 1024  # 200MB safety cap
DOWNLOAD_TIMEOUT_S = 30

VENV_DIR = Path("/home/lucid/lucid-agent-core/venv")
SYSTEM_USER = "lucid"


class ValidationError(ValueError):
    """Raised when upgrade payload validation fails."""


# GitHub release configuration for core
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
        """Derive wheel filename from package name and version."""
        return f"{CORE_PACKAGE_NAME}-{self.version}-py3-none-any.whl"

    @property
    def wheel_url(self) -> str:
        """Construct wheel URL from release_type, owner, repo, tag, and wheel filename."""
        if self.release_type != "github_release":
            raise ValidationError(f"unsupported release_type: {self.release_type}")
        tag = f"v{self.version}"
        return f"https://github.com/{CORE_GITHUB_OWNER}/{CORE_GITHUB_REPO}/releases/download/{tag}/{self.wheel_filename}"


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


def _parse_and_validate(raw_payload: str) -> UpgradeRequest:
    try:
        obj = json.loads(raw_payload) if raw_payload else {}
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise ValidationError("payload must be a dict")

    request_id = obj.get("request_id", "")
    release_type = obj.get("release_type", "github_release")  # Default to github_release
    version = obj.get("version", "")
    sha256 = obj.get("sha256", "")

    req = UpgradeRequest(
        request_id=request_id,
        release_type=release_type,
        version=version,
        sha256=sha256,
    )
    req.validate()
    return req


def _download_with_limits(url: str, out_path: Path, *, timeout_s: int, max_bytes: int) -> None:
    req = Request(url, headers={"User-Agent": "lucid-agent-core/upgrader"})
    read = 0
    with urlopen(req, timeout=timeout_s) as resp, out_path.open("wb") as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            read += len(chunk)
            if read > max_bytes:
                raise RuntimeError(f"download exceeded max_bytes={max_bytes}")
            f.write(chunk)


def _verify_sha256(path: Path, *, expected: str) -> None:
    expected_l = expected.lower()
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    got = h.hexdigest().lower()
    if got != expected_l:
        raise RuntimeError(f"sha256 mismatch: got={got}, expected={expected_l}")


def _pip_upgrade(wheel_path: Path) -> tuple[Optional[str], Optional[str]]:
    pip = VENV_DIR / "bin" / "pip"
    if not pip.exists():
        raise FileNotFoundError(f"pip executable not found: {pip}")

    completed = subprocess.run(
        [str(pip), "install", "--upgrade", str(wheel_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"pip install failed rc={completed.returncode}\n"
            f"stdout:\n{(completed.stdout or '').strip()}\n"
            f"stderr:\n{(completed.stderr or '').strip()}"
        )

    return completed.stdout, completed.stderr


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def handle_core_upgrade(raw_payload: str) -> UpgradeResult:
    """
    Validate payload, download wheel, verify SHA256, upgrade venv, return result.
    Always requires restart.
    """
    ts = _utc_now()

    try:
        req = _parse_and_validate(raw_payload)
    except ValidationError as exc:
        return UpgradeResult(
            request_id=json.loads(raw_payload).get("request_id", "") if raw_payload else "",
            version=json.loads(raw_payload).get("version", "") if raw_payload else "",
            ok=False,
            ts=ts,
            error=f"validation_error: {exc}",
            restart_required=True,
        )

    try:
        with tempfile.TemporaryDirectory() as tmp:
            wheel_filename = req.wheel_url.split("/")[-1]
            wheel_path = Path(tmp) / wheel_filename
            _download_with_limits(req.wheel_url, wheel_path, timeout_s=DOWNLOAD_TIMEOUT_S, max_bytes=MAX_WHEEL_BYTES)
            _verify_sha256(wheel_path, expected=req.sha256)
            pip_out, pip_err = _pip_upgrade(wheel_path)

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
