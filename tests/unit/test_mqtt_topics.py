import pytest

from lucid_agent_core.mqtt_topics import TopicSchema, TopicSchemaError


def test_agent_topic_paths() -> None:
    t = TopicSchema("agent_1")

    assert t.base == "lucid/agents/agent_1"
    assert t.metadata() == "lucid/agents/agent_1/metadata"
    assert t.status() == "lucid/agents/agent_1/status"
    assert t.state() == "lucid/agents/agent_1/state"
    assert t.cfg() == "lucid/agents/agent_1/cfg"
    assert t.cfg_telemetry() == "lucid/agents/agent_1/cfg/telemetry"
    assert t.logs() == "lucid/agents/agent_1/logs"
    assert t.telemetry("cpu") == "lucid/agents/agent_1/telemetry/cpu"

    assert t.cmd_ping() == "lucid/agents/agent_1/cmd/ping"
    assert t.cmd_restart() == "lucid/agents/agent_1/cmd/restart"
    assert t.cmd_refresh() == "lucid/agents/agent_1/cmd/refresh"
    assert t.cmd_components_install() == "lucid/agents/agent_1/cmd/components/install"
    assert t.cmd_components_uninstall() == "lucid/agents/agent_1/cmd/components/uninstall"
    assert t.cmd_components_enable() == "lucid/agents/agent_1/cmd/components/enable"
    assert t.cmd_components_disable() == "lucid/agents/agent_1/cmd/components/disable"

    assert t.evt_result("ping") == "lucid/agents/agent_1/evt/ping/result"
    assert t.evt_result("restart") == "lucid/agents/agent_1/evt/restart/result"
    assert t.evt_components_result("install") == "lucid/agents/agent_1/evt/components/install/result"
    assert t.evt_components_result("uninstall") == "lucid/agents/agent_1/evt/components/uninstall/result"


def test_component_topic_paths() -> None:
    t = TopicSchema("agent_1")

    assert t.component_base("cpu") == "lucid/agents/agent_1/components/cpu"
    assert t.component_cmd_reset("cpu") == "lucid/agents/agent_1/components/cpu/cmd/reset"
    assert t.component_cmd_ping("cpu") == "lucid/agents/agent_1/components/cpu/cmd/ping"
    assert t.component_cmd_cfg_set("cpu") == "lucid/agents/agent_1/components/cpu/cmd/cfg/set"
    assert t.component_cmd("led_strip", "clear") == "lucid/agents/agent_1/components/led_strip/cmd/clear"
    assert t.component_cmd("led_strip", "effect/glow") == "lucid/agents/agent_1/components/led_strip/cmd/effect/glow"


@pytest.mark.parametrize("bad", ["", "a/b", "a b", "..", "agent-1"])
def test_agent_id_validation(bad: str) -> None:
    with pytest.raises(TopicSchemaError):
        TopicSchema(bad)


@pytest.mark.parametrize("bad", ["", "CPU", "a/b", "a b", "..", "a-b"])
def test_component_id_validation(bad: str) -> None:
    t = TopicSchema("agent_1")
    with pytest.raises(TopicSchemaError):
        t.component_base(bad)
