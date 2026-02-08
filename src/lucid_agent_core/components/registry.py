from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path("/var/lib/lucid/components.json")


def load_registry() -> dict[str, dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return {}
    with REGISTRY_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    return data


def write_registry(data: dict[str, dict[str, Any]]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(REGISTRY_PATH.parent),
    ) as temp_file:
        json.dump(data, temp_file, indent=2, sort_keys=True)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_path = Path(temp_file.name)

    os.replace(temp_path, REGISTRY_PATH)


def is_same_install(
    existing: dict[str, Any] | None,
    repo: str,
    version: str,
    entrypoint: str,
) -> bool:
    if not isinstance(existing, dict):
        return False
    return (
        existing.get("repo") == repo
        and existing.get("version") == version
        and existing.get("entrypoint") == entrypoint
    )
