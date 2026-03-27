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


def fetch_release_asset(owner: str, repo: str, tag: str) -> str:
    """
    Return the .whl asset filename for *tag* from the GitHub releases API.

    Raises ValidationError if the API call fails or no .whl asset is found.
    """
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
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise ValidationError(
            f"failed to fetch release {tag} from {owner}/{repo}: {exc}"
        ) from exc

    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".whl"):
            return name

    raise ValidationError(f"no .whl asset found in release {tag} of {owner}/{repo}")


def build_wheel_url(owner: str, repo: str, tag: str, wheel_filename: str) -> str:
    """Construct the GitHub release download URL for a wheel."""
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{wheel_filename}"
