import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lucid_agent_core.core.component_installer as ci


def valid_payload(**overrides):
    base = {
        "request_id": "req-1",
        "component_id": "cpu",
        "source": {
            "type": "github_release",
            "owner": "LucidLabPlatform",
            "repo": "lucid-agent-cpu",
            "version": "1.2.3",
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


def test_validation_bad_version_rejected(monkeypatch):
    p = json.loads(valid_payload())
    p["source"]["version"] = "not-semver"
    res = ci.handle_install_component(json.dumps(p))

    assert res.ok is False
    assert "validation_error" in (res.error or "")


def test_idempotent_install_skips_work(monkeypatch):
    monkeypatch.setattr(
        ci,
        "load_registry",
        lambda: {"cpu": {"repo": "LucidLabPlatform/lucid-agent-cpu", "version": "1.2.3", "entrypoint": "some.module:CPU"}},
    )
    monkeypatch.setattr(ci, "is_same_install", lambda existing, repo, version, entrypoint: True)

    fetch = MagicMock()
    monkeypatch.setattr(ci, "_fetch_release_asset", fetch)

    download = MagicMock()
    monkeypatch.setattr(ci, "_download_with_limits", download)

    pip = MagicMock()
    monkeypatch.setattr(ci, "_pip_install", pip)

    write = MagicMock()
    monkeypatch.setattr(ci, "write_registry", write)

    res = ci.handle_install_component(valid_payload())

    assert res.ok is True
    assert res.restart_required is False

    fetch.assert_not_called()
    download.assert_not_called()
    pip.assert_not_called()
    write.assert_not_called()


def test_github_api_failure_returns_error(monkeypatch):
    monkeypatch.setattr(ci, "load_registry", lambda: {})
    monkeypatch.setattr(ci, "is_same_install", lambda *a: False)

    monkeypatch.setattr(
        ci,
        "_fetch_release_asset",
        lambda owner, repo, tag: (_ for _ in ()).throw(ci.ValidationError("failed to fetch release")),
    )

    res = ci.handle_install_component(valid_payload())

    assert res.ok is False
    assert "failed to fetch release" in (res.error or "")


def test_sha_mismatch_fails_before_pip(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "load_registry", lambda: {})
    monkeypatch.setattr(ci, "is_same_install", lambda *a: False)
    monkeypatch.setattr(ci, "_fetch_release_asset", lambda *a: "lucid_agent_cpu-1.2.3-py3-none-any.whl")

    def fake_download(url, out_path: Path, *, timeout_s: int, max_bytes: int):
        out_path.write_bytes(b"wheel-bytes")

    monkeypatch.setattr(ci, "_download_with_limits", fake_download)

    def fake_verify_sha(path: Path, *, expected: str):
        raise RuntimeError("sha256 mismatch: expected=... got=...")

    monkeypatch.setattr(ci, "_verify_sha256", fake_verify_sha)

    pip = MagicMock()
    monkeypatch.setattr(ci, "_pip_install", pip)

    monkeypatch.setattr(ci, "write_registry", MagicMock())

    res = ci.handle_install_component(valid_payload())

    assert res.ok is False
    assert "sha256 mismatch" in (res.error or "")
    pip.assert_not_called()


def test_pip_failure_returns_error_and_no_registry_write(monkeypatch):
    monkeypatch.setattr(ci, "load_registry", lambda: {})
    monkeypatch.setattr(ci, "is_same_install", lambda *a: False)
    monkeypatch.setattr(ci, "_fetch_release_asset", lambda *a: "lucid_agent_cpu-1.2.3-py3-none-any.whl")
    monkeypatch.setattr(ci, "_download_with_limits", lambda *a, **k: None)
    monkeypatch.setattr(ci, "_verify_sha256", lambda *a, **k: None)

    write = MagicMock()
    monkeypatch.setattr(ci, "write_registry", write)

    def fake_pip_install(path: Path, *, component_id: str = ""):
        raise RuntimeError("pip install failed rc=1\nstdout:\n...\nstderr:\nboom")

    monkeypatch.setattr(ci, "_pip_install", fake_pip_install)

    discover = MagicMock()
    monkeypatch.setattr(ci, "_discover_entrypoint", discover)

    res = ci.handle_install_component(valid_payload())

    assert res.ok is False
    assert "pip install failed" in (res.error or "")
    assert res.restart_required is False

    discover.assert_not_called()
    write.assert_not_called()


def test_missing_entrypoint_returns_error(monkeypatch):
    monkeypatch.setattr(ci, "load_registry", lambda: {})
    monkeypatch.setattr(ci, "is_same_install", lambda *a: False)
    monkeypatch.setattr(ci, "_fetch_release_asset", lambda *a: "lucid_agent_cpu-1.2.3-py3-none-any.whl")
    monkeypatch.setattr(ci, "_download_with_limits", lambda *a, **k: None)
    monkeypatch.setattr(ci, "_verify_sha256", lambda *a, **k: None)
    monkeypatch.setattr(ci, "_pip_install", lambda *a, **k: ("ok", ""))

    def fake_discover(component_id):
        raise ci.ValidationError("no entry point for component_id='cpu'")

    monkeypatch.setattr(ci, "_discover_entrypoint", fake_discover)
    monkeypatch.setattr(ci, "write_registry", MagicMock())

    res = ci.handle_install_component(valid_payload())

    assert res.ok is False
    assert "no entry point" in (res.error or "")


def test_success_updates_registry_and_requests_restart(monkeypatch):
    monkeypatch.setattr(ci, "load_registry", lambda: {})
    monkeypatch.setattr(ci, "is_same_install", lambda *a: False)
    monkeypatch.setattr(ci, "_fetch_release_asset", lambda *a: "lucid_agent_cpu-1.2.3-py3-none-any.whl")
    monkeypatch.setattr(ci, "_download_with_limits", lambda *a, **k: None)
    monkeypatch.setattr(ci, "_verify_sha256", lambda *a, **k: None)
    monkeypatch.setattr(ci, "_pip_install", lambda *a, **k: ("ok", ""))
    monkeypatch.setattr(ci, "_discover_entrypoint", lambda cid: "some.module:CPU")
    monkeypatch.setattr(ci, "_verify_entrypoint", lambda *a: None)

    written = {}

    def fake_write(reg):
        written.update(reg)

    monkeypatch.setattr(ci, "write_registry", fake_write)

    res = ci.handle_install_component(valid_payload())

    assert res.ok is True
    assert res.restart_required is True
    assert res.version == "1.2.3"
    assert "cpu" in written

    cpu = written["cpu"]
    assert cpu["version"] == "1.2.3"
    assert cpu["entrypoint"] == "some.module:CPU"
    assert cpu["sha256"] == ("a" * 64)
    assert cpu["repo"] == "LucidLabPlatform/lucid-agent-cpu"
    assert cpu["dist_name"] == "lucid-agent-cpu"
    assert cpu["source"]["type"] == "github_release"
    assert cpu["source"]["tag"] == "v1.2.3"
    assert cpu["source"]["asset"] == "lucid_agent_cpu-1.2.3-py3-none-any.whl"


def test_extract_version_best_effort_reads_from_source():
    raw = json.dumps({"source": {"version": "2.0.0"}})
    assert ci._extract_version_best_effort(raw) == "2.0.0"


def test_extract_version_best_effort_missing_returns_empty():
    assert ci._extract_version_best_effort("{}") == ""
    assert ci._extract_version_best_effort("not json") == ""
