import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import lucid_agent_core.core.component_installer as ci


def valid_payload(**overrides):
    base = {
        "request_id": "req-1",
        "component_id": "cpu",
        "version": "1.2.3",
        "entrypoint": "some.module:CPU",
        "source": {
            "type": "github_release",
            "owner": "LucidLabPlatform",
            "repo": "lucid-agent-cpu",
            "tag": "v1.2.3",
            "asset": "lucid_agent_cpu-1.2.3-py3-none-any.whl",
            "sha256": "a" * 64,
        },
    }
    base.update(overrides)
    return json.dumps(base)


def test_validation_missing_keys_returns_error(monkeypatch):
    payload = json.dumps({"foo": "bar"})

    res = ci.handle_install_component(payload)

    assert res.ok is False
    assert "validation_error" in (res.error or "")


def test_validation_bad_sha_rejected(monkeypatch):
    p = json.loads(valid_payload())
    p["source"]["sha256"] = "not-a-sha"
    res = ci.handle_install_component(json.dumps(p))

    assert res.ok is False
    assert "validation_error" in (res.error or "")


def test_idempotent_install_skips_work(monkeypatch):
    # registry indicates same install already applied
    monkeypatch.setattr(ci, "load_registry", lambda: {"cpu": {"repo": "LucidLabPlatform/lucid-agent-cpu", "version": "1.2.3", "entrypoint": "some.module:CPU"}})
    monkeypatch.setattr(ci, "is_same_install", lambda existing, repo, version, entrypoint: True)

    download = MagicMock()
    monkeypatch.setattr(ci, "_download_with_limits", download)

    pip = MagicMock()
    monkeypatch.setattr(ci, "_pip_install", pip)

    verify_ep = MagicMock()
    monkeypatch.setattr(ci, "_verify_entrypoint", verify_ep)

    write = MagicMock()
    monkeypatch.setattr(ci, "write_registry", write)

    res = ci.handle_install_component(valid_payload())

    assert res.ok is True
    assert res.restart_required is False

    download.assert_not_called()
    pip.assert_not_called()
    verify_ep.assert_not_called()
    write.assert_not_called()


def test_sha_mismatch_fails_before_pip(monkeypatch, tmp_path):
    # Force download to write a file, then sha check fails
    def fake_download(url, out_path: Path, *, timeout_s: int, max_bytes: int):
        out_path.write_bytes(b"wheel-bytes")

    monkeypatch.setattr(ci, "_download_with_limits", fake_download)

    def fake_verify_sha(path: Path, *, expected: str):
        raise RuntimeError("sha256 mismatch: expected=... got=...")

    monkeypatch.setattr(ci, "_verify_sha256", fake_verify_sha)

    pip = MagicMock()
    monkeypatch.setattr(ci, "_pip_install", pip)

    monkeypatch.setattr(ci, "load_registry", lambda: {})
    monkeypatch.setattr(ci, "write_registry", MagicMock())

    res = ci.handle_install_component(valid_payload())

    assert res.ok is False
    assert "sha256 mismatch" in (res.error or "")
    pip.assert_not_called()


def test_pip_failure_returns_error_and_no_registry_write(monkeypatch):
    monkeypatch.setattr(ci, "load_registry", lambda: {})
    write = MagicMock()
    monkeypatch.setattr(ci, "write_registry", write)

    # download + sha OK
    monkeypatch.setattr(ci, "_download_with_limits", lambda *a, **k: None)
    monkeypatch.setattr(ci, "_verify_sha256", lambda *a, **k: None)

    # pip fails
    def fake_pip_install(path: Path, *, component_id: str = ""):
        raise RuntimeError("pip install failed rc=1\nstdout:\n...\nstderr:\nboom")

    monkeypatch.setattr(ci, "_pip_install", fake_pip_install)

    # entrypoint won't be checked if pip fails
    verify_ep = MagicMock()
    monkeypatch.setattr(ci, "_verify_entrypoint", verify_ep)

    res = ci.handle_install_component(valid_payload())

    assert res.ok is False
    assert "pip install failed" in (res.error or "")
    assert res.restart_required is False

    verify_ep.assert_not_called()
    write.assert_not_called()


def test_success_updates_registry_and_requests_restart(monkeypatch):
    monkeypatch.setattr(ci, "load_registry", lambda: {})
    written = {}

    def fake_write(reg):
        written.update(reg)

    monkeypatch.setattr(ci, "write_registry", fake_write)

    monkeypatch.setattr(ci, "_download_with_limits", lambda *a, **k: None)
    monkeypatch.setattr(ci, "_verify_sha256", lambda *a, **k: None)
    monkeypatch.setattr(ci, "_pip_install", lambda *a, **k: ("ok", ""))
    monkeypatch.setattr(ci, "_verify_entrypoint", lambda *a, **k: None)

    res = ci.handle_install_component(valid_payload())

    assert res.ok is True
    assert res.restart_required is True
    assert "cpu" in written

    cpu = written["cpu"]
    assert cpu["version"] == "1.2.3"
    assert cpu["entrypoint"] == "some.module:CPU"
    assert cpu["sha256"] == ("a" * 64)
    assert cpu["repo"] == "LucidLabPlatform/lucid-agent-cpu"
    assert cpu["source"]["type"] == "github_release"
    assert cpu["source"]["tag"] == "v1.2.3"
