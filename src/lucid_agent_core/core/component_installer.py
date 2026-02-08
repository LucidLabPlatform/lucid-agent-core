from __future__ import annotations

import importlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from lucid_agent_core.components.registry import is_same_install, load_registry, write_registry

logger = logging.getLogger(__name__)

PIP_PATH = Path("/opt/lucid/agent-core/venv/bin/pip")
SERVICE_NAME = "lucid-agent-core"

COMPONENT_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
ENTRYPOINT_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)


class ValidationError(ValueError):
    """Raised when install_component payload validation fails."""


@dataclass(frozen=True)
class InstallRequest:
    component_id: str
    repo: str
    version: str
    entrypoint: str
    mode: str

    @property
    def package_name(self) -> str:
        return f"lucid_agent_{self.component_id}"

    @property
    def wheel_filename(self) -> str:
        return f"{self.package_name}-{self.version}-py3-none-any.whl"

    @property
    def wheel_url(self) -> str:
        url = (
            f"https://github.com/{self.repo}/releases/download/"
            f"v{self.version}/{self.wheel_filename}"
        )
        if not url.startswith("https://github.com/") or not url.endswith(".whl"):
            raise ValidationError("derived wheel URL must be a GitHub .whl URL")
        return url


def handle_install_component(raw_payload: str) -> None:
    try:
        request = _parse_and_validate(raw_payload)
    except ValidationError as exc:
        logger.error("Invalid install_component payload: %s", exc)
        return

    try:
        _install_component(request)
    except Exception as exc:
        logger.exception(
            "Failed to install component %s version %s: %s",
            request.component_id,
            request.version,
            exc,
        )


def _parse_and_validate(raw_payload: str) -> InstallRequest:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"payload must be valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object")

    required_keys = {"component_id", "repo", "version", "entrypoint", "mode"}
    if set(payload.keys()) != required_keys:
        raise ValidationError(
            f"payload keys must be exactly {sorted(required_keys)}, got {sorted(payload.keys())}"
        )

    component_id = payload["component_id"]
    repo = payload["repo"]
    version = payload["version"]
    entrypoint = payload["entrypoint"]
    mode = payload["mode"]

    _validate_string("component_id", component_id)
    _validate_string("repo", repo)
    _validate_string("version", version)
    _validate_string("entrypoint", entrypoint)
    _validate_string("mode", mode)

    if not COMPONENT_ID_PATTERN.fullmatch(component_id):
        raise ValidationError("component_id must match ^[a-z0-9_]+$")
    if not REPO_PATTERN.fullmatch(repo):
        raise ValidationError("repo must match ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    if not VERSION_PATTERN.fullmatch(version):
        raise ValidationError("version must match ^\\d+\\.\\d+\\.\\d+$")
    if ":" not in entrypoint or not ENTRYPOINT_PATTERN.fullmatch(entrypoint):
        raise ValidationError("entrypoint must be module:ClassName")
    if mode != "restart":
        raise ValidationError('mode must equal "restart"')

    return InstallRequest(
        component_id=component_id,
        repo=repo,
        version=version,
        entrypoint=entrypoint,
        mode=mode,
    )


def _validate_string(field_name: str, value: object) -> None:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")


def _install_component(request: InstallRequest) -> None:
    registry = load_registry()
    existing = registry.get(request.component_id)
    if is_same_install(existing, request.repo, request.version, request.entrypoint):
        logger.info(
            "Component %s already installed with requested repo/version/entrypoint; skipping",
            request.component_id,
        )
        return

    wheel_url = request.wheel_url
    logger.info(
        "Installing component %s version %s from %s",
        request.component_id,
        request.version,
        wheel_url,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        wheel_path = Path(temp_dir) / request.wheel_filename
        _download_wheel(wheel_url, wheel_path)
        _install_wheel(wheel_path)

    _verify_entrypoint(request.entrypoint)

    registry[request.component_id] = {
        "repo": request.repo,
        "version": request.version,
        "wheel_url": wheel_url,
        "entrypoint": request.entrypoint,
        "installed_at": _utc_now(),
    }
    write_registry(registry)

    logger.info("Restarting service %s", SERVICE_NAME)
    _restart_service()
    logger.info("Component %s install completed", request.component_id)


def _download_wheel(wheel_url: str, wheel_path: Path) -> None:
    with urlopen(wheel_url) as response, wheel_path.open("wb") as output_file:
        shutil.copyfileobj(response, output_file)


def _install_wheel(wheel_path: Path) -> None:
    if not PIP_PATH.exists():
        raise FileNotFoundError(f"pip executable not found: {PIP_PATH}")

    completed = subprocess.run(
        [str(PIP_PATH), "install", "--upgrade", str(wheel_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    if completed.stdout:
        logger.info("pip install stdout: %s", completed.stdout.strip())
    if completed.stderr:
        logger.info("pip install stderr: %s", completed.stderr.strip())


def _verify_entrypoint(entrypoint: str) -> None:
    module_name, class_name = entrypoint.split(":", 1)
    module = importlib.import_module(module_name)
    getattr(module, class_name)


def _restart_service() -> None:
    subprocess.run(
        ["systemctl", "restart", SERVICE_NAME],
        check=True,
        capture_output=True,
        text=True,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

