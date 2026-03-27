"""
Download and verification utilities for wheel files.

Provides size-limited HTTP downloads and SHA256 integrity checks
used by all installer and upgrader modules.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.request import Request, urlopen

MAX_WHEEL_BYTES = 200 * 1024 * 1024  # 200 MB safety cap
DOWNLOAD_TIMEOUT_S = 30


def download_wheel(
    url: str,
    out_path: Path,
    *,
    timeout_s: int = DOWNLOAD_TIMEOUT_S,
    max_bytes: int = MAX_WHEEL_BYTES,
    user_agent: str = "lucid-agent-core",
) -> None:
    """Download a wheel from *url* into *out_path*, aborting if size exceeds *max_bytes*."""
    req = Request(url, headers={"User-Agent": user_agent})
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


def verify_sha256(path: Path, *, expected: str) -> None:
    """Raise RuntimeError if *path*'s SHA256 does not match *expected*."""
    expected_l = expected.lower()
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    got = h.hexdigest().lower()
    if got != expected_l:
        raise RuntimeError(f"sha256 mismatch: got={got}, expected={expected_l}")
