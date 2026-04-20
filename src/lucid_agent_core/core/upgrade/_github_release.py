"""
GitHub releases API helper.

Fetches the .whl asset filename from the GitHub releases API for a given
owner/repo/tag, used during component installation.
"""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from lucid_agent_core.core.upgrade._download import DOWNLOAD_TIMEOUT_S
from lucid_agent_core.core.upgrade._validation import ValidationError

try:
    from importlib.metadata import version as _pkg_version

    _AGENT_VERSION = _pkg_version("lucid-agent-core")
except Exception:
    _AGENT_VERSION = "0.0.0"


def _fetch_release_data(owner: str, repo: str, tag: str) -> dict:
    """Fetch and return the GitHub release JSON for *tag*."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    api_req = Request(
        url,
        headers={
            "User-Agent": f"lucid-agent-core/{_AGENT_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urlopen(api_req, timeout=DOWNLOAD_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise ValidationError(
            f"failed to fetch release {tag} from {owner}/{repo}: {exc}"
        ) from exc


def fetch_release_asset(owner: str, repo: str, tag: str) -> str:
    """
    Return the .whl asset filename for *tag* from the GitHub releases API.

    Raises ValidationError if the API call fails or no .whl asset is found.
    """
    data = _fetch_release_data(owner, repo, tag)
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".whl"):
            return name
    raise ValidationError(f"no .whl asset found in release {tag} of {owner}/{repo}")


def fetch_release_wheel_sha256(owner: str, repo: str, tag: str) -> tuple[str, str]:
    """
    Return (wheel_filename, sha256_hex) for the .whl asset in *tag*.

    SHA256 is read from the asset's 'digest' field (sha256:<hex>).
    Raises ValidationError if the release, asset, or digest is missing.
    """
    data = _fetch_release_data(owner, repo, tag)
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if not name.endswith(".whl"):
            continue
        digest = asset.get("digest", "")
        if digest.startswith("sha256:"):
            return name, digest[7:]
        raise ValidationError(
            f"no sha256 digest on .whl asset '{name}' in release {tag} of {owner}/{repo}"
        )
    raise ValidationError(f"no .whl asset found in release {tag} of {owner}/{repo}")


def build_wheel_url(owner: str, repo: str, tag: str, wheel_filename: str) -> str:
    """Construct the GitHub release download URL for a wheel."""
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{wheel_filename}"
