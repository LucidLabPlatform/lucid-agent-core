"""
Component upgrade handler.

Downloads wheel from GitHub release, verifies SHA256, upgrades venv, updates registry, restarts service.
Same pattern as core upgrade but for components.
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

from lucid_agent_core.components.registry import load_registry, write_registry
from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)

_COMPONENT_ID_RE = re.compile(r"^[a-z0-9_]+$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")

MAX_WHEEL_BYTES = 200 * 1024 * 1024  # 200MB safety cap
DOWNLOAD_TIMEOUT_S = 30


class ValidationError(ValueError):
    """Raised when upgrade payload validation fails."""


@dataclass(frozen=True, slots=True)
class ComponentUpgradeRequest:
    request_id: str
    component_id: str
    release_type: str
    version: str
    sha256: str
    owner: str  # From registry
    repo: str  # From registry
    dist_name: str  # From registry

    def validate(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValidationError("request_id must be a non-empty string")
        if not isinstance(self.component_id, str) or not _COMPONENT_ID_RE.fullmatch(self.component_id):
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
        """Derive wheel filename from dist_name and version."""
        # Convert dist_name (e.g., "lucid-component-fixture-cpu") to wheel format
        # Wheel format: underscores instead of hyphens
        wheel_name = self.dist_name.replace("-", "_")
        return f"{wheel_name}-{self.version}-py3-none-any.whl"

    @property
    def wheel_url(self) -> str:
        """Construct wheel URL from release_type, owner, repo, tag, and wheel filename."""
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


def _parse_and_validate(raw_payload: str) -> ComponentUpgradeRequest:
    """
    Parse and validate upgrade payload, then enrich with registry data.
    Payload: { request_id, component_id, release_type, version, sha256 }
    Registry provides: owner, repo, dist_name
    """
    try:
        obj = json.loads(raw_payload) if raw_payload else {}
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise ValidationError("payload must be a dict")

    request_id = obj.get("request_id", "")
    component_id = obj.get("component_id", "")
    release_type = obj.get("release_type", "github_release")  # Default to github_release
    version = obj.get("version", "")
    sha256 = obj.get("sha256", "")

    # Load registry to get owner, repo, dist_name
    registry = load_registry()
    if component_id not in registry:
        raise ValidationError(f"component not found in registry: {component_id}")

    component_info = registry[component_id]
    repo_str = component_info.get("repo", "")
    if not repo_str or "/" not in repo_str:
        raise ValidationError(f"invalid repo format in registry for {component_id}: {repo_str}")
    
    owner, repo = repo_str.split("/", 1)
    dist_name = component_info.get("dist_name", "")
    if not dist_name:
        raise ValidationError(f"dist_name not found in registry for {component_id}")

    req = ComponentUpgradeRequest(
        request_id=request_id,
        component_id=component_id,
        release_type=release_type,
        version=version,
        sha256=sha256,
        owner=owner,
        repo=repo,
        dist_name=dist_name,
    )
    req.validate()
    return req


def _download_with_limits(url: str, out_path: Path, *, timeout_s: int, max_bytes: int) -> None:
    req = Request(url, headers={"User-Agent": "lucid-agent-core/component-upgrader"})
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
    paths = get_paths()
    pip_path = paths.pip_path
    
    if not pip_path.exists():
        raise FileNotFoundError(f"pip executable not found: {pip_path}")

    completed = subprocess.run(
        [str(pip_path), "install", "--upgrade", str(wheel_path)],
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


def _extract_dist_name_from_wheel(wheel_filename: str) -> str:
    """
    Extract distribution name from wheel filename.
    Example: lucid_component_fixture_cpu-0.5.2-py3-none-any.whl -> lucid-component-fixture-cpu
    """
    # Remove .whl extension
    name = wheel_filename.replace(".whl", "")
    # Split by - and take everything before the version (first occurrence of -X.Y.Z pattern)
    parts = name.split("-")
    # Find where version starts (first part that matches semver pattern)
    for i, part in enumerate(parts):
        if re.match(r"^\d+\.\d+\.\d+", part):
            # Everything before this is the dist name
            dist_parts = parts[:i]
            # Join with hyphens (wheel name format)
            return "-".join(dist_parts)
    # Fallback: take all parts except last 3 (version, python tag, abi/platform)
    if len(parts) >= 4:
        return "-".join(parts[:-3])
    return name


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def handle_component_upgrade(raw_payload: str) -> ComponentUpgradeResult:
    """
    Validate payload, download wheel, verify SHA256, upgrade venv, update registry, return result.
    Always requires restart.
    """
    ts = _utc_now()

    try:
        req = _parse_and_validate(raw_payload)
    except ValidationError as exc:
        try:
            payload_obj = json.loads(raw_payload) if raw_payload else {}
        except json.JSONDecodeError:
            payload_obj = {}
        return ComponentUpgradeResult(
            request_id=payload_obj.get("request_id", ""),
            component_id=payload_obj.get("component_id", ""),
            version=payload_obj.get("version", ""),
            ok=False,
            ts=ts,
            error=f"validation_error: {exc}",
            restart_required=True,
        )

    try:
        with tempfile.TemporaryDirectory() as tmp:
            wheel_filename = req.wheel_filename
            wheel_path = Path(tmp) / wheel_filename
            _download_with_limits(req.wheel_url, wheel_path, timeout_s=DOWNLOAD_TIMEOUT_S, max_bytes=MAX_WHEEL_BYTES)
            _verify_sha256(wheel_path, expected=req.sha256)
            pip_out, pip_err = _pip_upgrade(wheel_path)

        # Update registry with new version
        registry = load_registry()
        registry[req.component_id]["version"] = req.version
        registry[req.component_id]["wheel_url"] = req.wheel_url
        registry[req.component_id]["sha256"] = req.sha256.lower()
        # Keep existing dist_name, entrypoint and other fields
        write_registry(registry)

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
