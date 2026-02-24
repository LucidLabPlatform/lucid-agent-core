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

try:
    from importlib.metadata import version as _pkg_version
    _AGENT_VERSION = _pkg_version("lucid-agent-core")
except Exception:  # PackageNotFoundError or missing metadata
    _AGENT_VERSION = "0.0.0"

from lucid_agent_core.components.registry import is_same_install, load_registry, write_registry
from lucid_agent_core.paths import get_paths

logger = logging.getLogger(__name__)

_COMPONENT_ID_RE = re.compile(r"^[a-z0-9_]+$")
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
        if not isinstance(self.component_id, str) or not _COMPONENT_ID_RE.fullmatch(self.component_id):
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

    tag = f"v{req.source.version}"
    wheel_url: Optional[str] = None

    try:
        registry = load_registry()
        existing = registry.get(req.component_id)

        # Idempotency: if same repo + version already installed, do nothing.
        existing_entrypoint = existing.get("entrypoint", "") if isinstance(existing, dict) else ""
        if is_same_install(existing, f"{req.source.owner}/{req.source.repo}", req.source.version, existing_entrypoint):
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

        # Fetch asset filename from GitHub releases API
        asset = _fetch_release_asset(req.source.owner, req.source.repo, tag)
        wheel_url = f"https://github.com/{req.source.owner}/{req.source.repo}/releases/download/{tag}/{asset}"

        with tempfile.TemporaryDirectory() as tmp:
            wheel_path = Path(tmp) / asset
            _download_with_limits(wheel_url, wheel_path, timeout_s=DOWNLOAD_TIMEOUT_S, max_bytes=MAX_WHEEL_BYTES)
            _verify_sha256(wheel_path, expected=req.source.sha256)
            pip_out, pip_err = _pip_install(wheel_path, component_id=req.component_id)

        entrypoint = _discover_entrypoint(req.component_id)
        _verify_entrypoint(entrypoint)

        dist_name = _extract_dist_name_from_wheel(asset)

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
        logger.exception("Install failed component=%s version=%s", req.component_id, req.source.version)
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


def _fetch_release_asset(owner: str, repo: str, tag: str) -> str:
    """Fetch .whl asset filename from GitHub releases API for the given tag."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    api_req = Request(url, headers={
        "User-Agent": f"lucid-agent-core/{_AGENT_VERSION}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urlopen(api_req, timeout=DOWNLOAD_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise ValidationError(f"failed to fetch release {tag} from {owner}/{repo}: {exc}") from exc

    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".whl"):
            return name

    raise ValidationError(f"no .whl asset found in release {tag} of {owner}/{repo}")


def _discover_entrypoint(component_id: str) -> str:
    """Discover component entrypoint via importlib.metadata entry_points after install."""
    from importlib.metadata import entry_points
    for ep in entry_points(group="lucid_components"):
        if ep.name == component_id:
            return ep.value
    raise ValidationError(
        f"no entry point for component_id={component_id!r} in group 'lucid_components'; "
        "ensure the wheel declares [project.entry-points.\"lucid_components\"]"
    )


def _download_with_limits(url: str, out_path: Path, *, timeout_s: int, max_bytes: int) -> None:
    req = Request(url, headers={"User-Agent": f"lucid-agent-core/{_AGENT_VERSION}"})
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


def _pip_install(wheel_path: Path, *, component_id: str) -> tuple[Optional[str], Optional[str]]:
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

    out_lines = [completed.stdout or ""]
    err_lines = [completed.stderr or ""]

    # Install [pi] extra for led_strip so the helper has rpi_ws281x in the same venv.
    if component_id == "led_strip":
        extra_completed = subprocess.run(
            [str(pip_path), "install", "lucid-component-led-strip[pi]"],
            check=False,
            capture_output=True,
            text=True,
        )
        if extra_completed.returncode != 0:
            logger.warning(
                "pip install lucid-component-led-strip[pi] failed (helper may lack rpi_ws281x): %s",
                (extra_completed.stderr or extra_completed.stdout or "").strip(),
            )
        else:
            out_lines.append(extra_completed.stdout or "")
            err_lines.append(extra_completed.stderr or "")

    return "\n".join(out_lines).strip() or None, "\n".join(err_lines).strip() or None


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
        if isinstance(obj, dict):
            source = obj.get("source", {})
            if isinstance(source, dict) and isinstance(source.get("version"), str):
                return source["version"]
    except Exception:
        pass
    return ""


def _extract_dist_name_from_wheel(wheel_filename: str) -> str:
    """
    Extract distribution name from wheel filename.
    Wheel format: {distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl
    """
    if wheel_filename.endswith(".whl"):
        wheel_filename = wheel_filename[:-4]
    parts = wheel_filename.split("-", 1)
    return parts[0].replace("_", "-")
