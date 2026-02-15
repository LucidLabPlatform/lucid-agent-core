"""
Component installer — handles MQTT install commands.

Downloads wheels from GitHub releases, verifies SHA256, runs pip install,
updates the registry, and optionally triggers agent restart.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.request import Request, urlopen

from lucid_agent_core.components.registry import is_same_install, load_registry, write_registry
from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)

_COMPONENT_ID_RE = re.compile(r"^[a-z0-9_]+$")
_ENTRYPOINT_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_GH_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

MAX_WHEEL_BYTES = 200 * 1024 * 1024  # 200MB safety cap
DOWNLOAD_TIMEOUT_S = 30


class ValidationError(ValueError):
    """Raised when install payload validation fails."""


@dataclass(frozen=True, slots=True)
class GithubReleaseSource:
    type: Literal["github_release"]
    owner: str
    repo: str
    tag: str
    asset: str
    sha256: str

    def validate(self) -> None:
        if self.type != "github_release":
            raise ValidationError('source.type must be "github_release"')
        if not _GH_NAME_RE.fullmatch(self.owner):
            raise ValidationError("source.owner is invalid")
        if not _GH_NAME_RE.fullmatch(self.repo):
            raise ValidationError("source.repo is invalid")
        if not isinstance(self.tag, str) or not self.tag:
            raise ValidationError("source.tag must be a non-empty string")
        if not isinstance(self.asset, str) or not self.asset.endswith(".whl"):
            raise ValidationError("source.asset must be a .whl filename")
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise ValidationError("source.sha256 must be 64 hex chars")


@dataclass(frozen=True, slots=True)
class InstallRequest:
    request_id: str
    component_id: str
    version: str
    entrypoint: str
    source: GithubReleaseSource

    def validate(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValidationError("request_id must be a non-empty string")
        if not isinstance(self.component_id, str) or not _COMPONENT_ID_RE.fullmatch(self.component_id):
            raise ValidationError(f"component_id must match ^[a-z0-9_]+$: {self.component_id}")
        if not isinstance(self.version, str) or not _SEMVER_RE.fullmatch(self.version):
            raise ValidationError("version must be semver like 1.2.3")
        if not isinstance(self.entrypoint, str) or not _ENTRYPOINT_RE.fullmatch(self.entrypoint):
            raise ValidationError("entrypoint must be module:ClassName")
        self.source.validate()

    @property
    def wheel_url(self) -> str:
        # Example: https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>
        url = f"https://github.com/{self.source.owner}/{self.source.repo}/releases/download/{self.source.tag}/{self.source.asset}"
        if not url.startswith("https://github.com/"):
            raise ValidationError("derived wheel URL must be a GitHub URL")
        return url


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
    Validates payload, downloads wheel, verifies integrity, installs, verifies entrypoint,
    updates registry, and returns a structured result.
    """
    ts = _utc_now()

    try:
        req = _parse_and_validate(raw_payload)
    except ValidationError as exc:
        # No request_id guaranteed. Return best-effort.
        return InstallResult(
            request_id=_extract_request_id_best_effort(raw_payload),
            component_id=_extract_component_id_best_effort(raw_payload),
            version=_extract_version_best_effort(raw_payload),
            ok=False,
            ts=ts,
            error=f"validation_error: {exc}",
            restart_required=False,
        )

    wheel_url = req.wheel_url

    try:
        registry = load_registry()
        existing = registry.get(req.component_id)

        # Idempotency: if same install already applied, do nothing.
        if is_same_install(existing, f"{req.source.owner}/{req.source.repo}", req.version, req.entrypoint):
            return InstallResult(
                request_id=req.request_id,
                component_id=req.component_id,
                version=req.version,
                ok=True,
                ts=ts,
                wheel_url=wheel_url,
                sha256=req.source.sha256.lower(),
                restart_required=False,
            )

        with tempfile.TemporaryDirectory() as tmp:
            wheel_path = Path(tmp) / req.source.asset
            _download_with_limits(wheel_url, wheel_path, timeout_s=DOWNLOAD_TIMEOUT_S, max_bytes=MAX_WHEEL_BYTES)
            _verify_sha256(wheel_path, expected=req.source.sha256)
            pip_out, pip_err = _pip_install(wheel_path)
        _verify_entrypoint(req.entrypoint)

        # Extract dist_name from wheel filename for uninstall
        # Example: lucid_agent_cpu-1.0.0-py3-none-any.whl -> lucid-agent-cpu
        dist_name = _extract_dist_name_from_wheel(req.source.asset)

        # Registry update: store source + checksum + dist_name for auditability
        registry[req.component_id] = {
            "repo": f"{req.source.owner}/{req.source.repo}",
            "version": req.version,
            "wheel_url": wheel_url,
            "entrypoint": req.entrypoint,
            "sha256": req.source.sha256.lower(),
            "dist_name": dist_name,
            "source": {
                "type": req.source.type,
                "owner": req.source.owner,
                "repo": req.source.repo,
                "tag": req.source.tag,
                "asset": req.source.asset,
            },
            "installed_at": ts,
        }
        write_registry(registry)

        return InstallResult(
            request_id=req.request_id,
            component_id=req.component_id,
            version=req.version,
            ok=True,
            ts=ts,
            wheel_url=wheel_url,
            sha256=req.source.sha256.lower(),
            pip_stdout=pip_out,
            pip_stderr=pip_err,
            restart_required=True,
        )

    except Exception as exc:
        logger.exception("Install failed component=%s version=%s", req.component_id, req.version)
        return InstallResult(
            request_id=req.request_id,
            component_id=req.component_id,
            version=req.version,
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

    # Strict-ish: required keys, but allow future extension by ignoring unknown keys.
    for key in ("request_id", "component_id", "version", "entrypoint", "source"):
        if key not in payload:
            raise ValidationError(f"missing required key: {key}")

    source_obj = payload["source"]
    if not isinstance(source_obj, dict):
        raise ValidationError("source must be an object")

    source = GithubReleaseSource(
        type=source_obj.get("type"),
        owner=source_obj.get("owner"),
        repo=source_obj.get("repo"),
        tag=source_obj.get("tag"),
        asset=source_obj.get("asset"),
        sha256=source_obj.get("sha256"),
    )

    req = InstallRequest(
        request_id=payload["request_id"],
        component_id=payload["component_id"],
        version=payload["version"],
        entrypoint=payload["entrypoint"],
        source=source,
    )
    req.validate()
    return req


def _download_with_limits(url: str, out_path: Path, *, timeout_s: int, max_bytes: int) -> None:
    req = Request(url, headers={"User-Agent": "lucid-agent-core/1.0.0"})
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
        raise RuntimeError(f"sha256 mismatch: got={got}")


def _pip_install(wheel_path: Path) -> tuple[Optional[str], Optional[str]]:
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


def _verify_entrypoint(entrypoint: str) -> None:
    module_name, class_name = entrypoint.split(":", 1)
    module = importlib.import_module(module_name)
    getattr(module, class_name)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_request_id_best_effort(raw_payload: str) -> str:
    try:
        obj = json.loads(raw_payload)
        if isinstance(obj, dict) and isinstance(obj.get("request_id"), str):
            return obj["request_id"]
    except Exception:
        pass
    return ""


def _extract_component_id_best_effort(raw_payload: str) -> str:
    try:
        obj = json.loads(raw_payload)
        if isinstance(obj, dict) and isinstance(obj.get("component_id"), str):
            return obj["component_id"]
    except Exception:
        pass
    return ""


def _extract_version_best_effort(raw_payload: str) -> str:
    try:
        obj = json.loads(raw_payload)
        if isinstance(obj, dict) and isinstance(obj.get("version"), str):
            return obj["version"]
    except Exception:
        pass
    return ""


def _extract_dist_name_from_wheel(wheel_filename: str) -> str:
    """
    Extract distribution name from wheel filename.

    Wheel format: {distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl
    Example: lucid_agent_cpu-1.0.0-py3-none-any.whl -> lucid-agent-cpu

    Args:
        wheel_filename: Wheel filename (e.g., "lucid_agent_cpu-1.0.0-py3-none-any.whl")

    Returns:
        Distribution name with underscores replaced by hyphens
    """
    # Strip .whl extension
    if wheel_filename.endswith(".whl"):
        wheel_filename = wheel_filename[:-4]

    # Split on first hyphen to get distribution name
    # (version always starts with a digit after the first hyphen)
    parts = wheel_filename.split("-", 1)
    if len(parts) < 1:
        raise ValueError(f"Invalid wheel filename format: {wheel_filename}")

    dist_name = parts[0]

    # PEP 503: normalize by replacing underscores with hyphens
    dist_name = dist_name.replace("_", "-")

    return dist_name
