import pytest

from lucid_agent_core.core import component_installer as installer


@pytest.mark.unit
def test_parse_and_validate_success():
    request = installer._parse_and_validate(
        """
        {
          "component_id": "led_strip",
          "repo": "LucidLabPlatform/lucid-agent-led",
          "version": "0.1.0",
          "entrypoint": "lucid_agent_led.component:LedStripComponent",
          "mode": "restart"
        }
        """
    )

    assert request.component_id == "led_strip"
    assert request.package_name == "lucid_agent_led_strip"
    assert request.wheel_filename == "lucid_agent_led_strip-0.1.0-py3-none-any.whl"
    assert (
        request.wheel_url
        == "https://github.com/LucidLabPlatform/lucid-agent-led/releases/download/"
        "v0.1.0/lucid_agent_led_strip-0.1.0-py3-none-any.whl"
    )


@pytest.mark.unit
def test_parse_and_validate_rejects_invalid_mode():
    with pytest.raises(installer.ValidationError):
        installer._parse_and_validate(
            """
            {
              "component_id": "led_strip",
              "repo": "LucidLabPlatform/lucid-agent-led",
              "version": "0.1.0",
              "entrypoint": "lucid_agent_led.component:LedStripComponent",
              "mode": "hotload"
            }
            """
        )


@pytest.mark.unit
def test_parse_and_validate_rejects_extra_keys():
    with pytest.raises(installer.ValidationError):
        installer._parse_and_validate(
            """
            {
              "component_id": "led_strip",
              "repo": "LucidLabPlatform/lucid-agent-led",
              "version": "0.1.0",
              "entrypoint": "lucid_agent_led.component:LedStripComponent",
              "mode": "restart",
              "wheel_url": "https://example.com/file.whl"
            }
            """
        )


@pytest.mark.unit
def test_handle_install_component_rejects_bad_payload(monkeypatch):
    called = {"install": False}

    def _install(_request):
        called["install"] = True

    monkeypatch.setattr(installer, "_install_component", _install)

    installer.handle_install_component('{"component_id":"bad"}')

    assert called["install"] is False


@pytest.mark.unit
def test_install_component_idempotent_noop(monkeypatch):
    request = installer.InstallRequest(
        component_id="led_strip",
        repo="LucidLabPlatform/lucid-agent-led",
        version="0.1.0",
        entrypoint="lucid_agent_led.component:LedStripComponent",
        mode="restart",
    )

    monkeypatch.setattr(
        installer,
        "load_registry",
        lambda: {
            "led_strip": {
                "repo": "LucidLabPlatform/lucid-agent-led",
                "version": "0.1.0",
                "entrypoint": "lucid_agent_led.component:LedStripComponent",
            }
        },
    )

    flags = {"download": False, "pip": False, "verify": False, "write": False, "restart": False}
    monkeypatch.setattr(installer, "_download_wheel", lambda *_: flags.__setitem__("download", True))
    monkeypatch.setattr(installer, "_install_wheel", lambda *_: flags.__setitem__("pip", True))
    monkeypatch.setattr(installer, "_verify_entrypoint", lambda *_: flags.__setitem__("verify", True))
    monkeypatch.setattr(installer, "write_registry", lambda *_: flags.__setitem__("write", True))
    monkeypatch.setattr(installer, "_restart_service", lambda *_: flags.__setitem__("restart", True))

    installer._install_component(request)

    assert flags == {"download": False, "pip": False, "verify": False, "write": False, "restart": False}


@pytest.mark.unit
def test_install_component_success(monkeypatch):
    request = installer.InstallRequest(
        component_id="led_strip",
        repo="LucidLabPlatform/lucid-agent-led",
        version="0.1.0",
        entrypoint="lucid_agent_led.component:LedStripComponent",
        mode="restart",
    )

    monkeypatch.setattr(installer, "load_registry", lambda: {})
    monkeypatch.setattr(installer, "_utc_now", lambda: "2026-02-06T16:30:00Z")

    calls = {"download": None, "install": None, "verify": None, "write": None, "restart": 0}

    def _download(url, path):
        calls["download"] = (url, path)

    def _install(path):
        calls["install"] = path

    def _verify(entrypoint):
        calls["verify"] = entrypoint

    def _write(data):
        calls["write"] = data

    def _restart():
        calls["restart"] += 1

    monkeypatch.setattr(installer, "_download_wheel", _download)
    monkeypatch.setattr(installer, "_install_wheel", _install)
    monkeypatch.setattr(installer, "_verify_entrypoint", _verify)
    monkeypatch.setattr(installer, "write_registry", _write)
    monkeypatch.setattr(installer, "_restart_service", _restart)

    installer._install_component(request)

    assert calls["download"] is not None
    assert calls["download"][0] == request.wheel_url
    assert str(calls["download"][1]).endswith(request.wheel_filename)
    assert calls["install"] == calls["download"][1]
    assert calls["verify"] == request.entrypoint
    assert calls["write"] == {
        "led_strip": {
            "repo": "LucidLabPlatform/lucid-agent-led",
            "version": "0.1.0",
            "wheel_url": request.wheel_url,
            "entrypoint": "lucid_agent_led.component:LedStripComponent",
            "installed_at": "2026-02-06T16:30:00Z",
        }
    }
    assert calls["restart"] == 1

