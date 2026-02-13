import pytest

from lucid_agent_core.mqtt_topics import TopicSchema, TopicSchemaError


def test_topics_core_paths() -> None:
    t = TopicSchema("agent_1")

    assert t.base == "lucid/agents/agent_1"
    assert t.status() == "lucid/agents/agent_1/status"

    assert t.core_metadata() == "lucid/agents/agent_1/core/metadata"
    assert t.core_state() == "lucid/agents/agent_1/core/state"
    assert t.core_components() == "lucid/agents/agent_1/core/components"

    assert t.core_cmd_root() == "lucid/agents/agent_1/core/cmd"
    assert t.core_evt_root() == "lucid/agents/agent_1/core/evt"
    assert t.core_log_root() == "lucid/agents/agent_1/core/log"
    assert t.core_cfg_root() == "lucid/agents/agent_1/core/cfg"

    assert t.core_cmd_refresh() == "lucid/agents/agent_1/core/cmd/refresh"
    assert t.core_evt_refresh_result() == "lucid/agents/agent_1/core/evt/refresh_result"

    assert t.core_cmd_components_install() == "lucid/agents/agent_1/core/cmd/components/install"
    assert t.core_evt_components_install_result() == "lucid/agents/agent_1/core/evt/components/install_result"

    assert t.core_cmd_components_uninstall() == "lucid/agents/agent_1/core/cmd/components/uninstall"
    assert t.core_evt_components_uninstall_result() == "lucid/agents/agent_1/core/evt/components/uninstall_result"


def test_topics_component_paths() -> None:
    t = TopicSchema("agent_1")

    assert t.component_base("cpu") == "lucid/agents/agent_1/components/cpu"

    assert t.component_cmd_root("cpu") == "lucid/agents/agent_1/components/cpu/cmd"
    assert t.component_evt_root("cpu") == "lucid/agents/agent_1/components/cpu/evt"

    assert t.component_metadata("cpu") == "lucid/agents/agent_1/components/cpu/metadata"
    assert t.component_state("cpu") == "lucid/agents/agent_1/components/cpu/state"

    assert t.component_cmd_start("cpu") == "lucid/agents/agent_1/components/cpu/cmd/start"
    assert t.component_evt_start_result("cpu") == "lucid/agents/agent_1/components/cpu/evt/start_result"

    assert t.component_cmd_stop("cpu") == "lucid/agents/agent_1/components/cpu/cmd/stop"
    assert t.component_evt_stop_result("cpu") == "lucid/agents/agent_1/components/cpu/evt/stop_result"


@pytest.mark.parametrize("bad", ["", "a/b", "a b", "..", "agent-1"])
def test_agent_username_validation(bad: str) -> None:
    with pytest.raises(TopicSchemaError):
        TopicSchema(bad)


@pytest.mark.parametrize("bad", ["", "CPU", "a/b", "a b", "..", "a-b"])
def test_component_id_validation(bad: str) -> None:
    t = TopicSchema("agent_1")
    with pytest.raises(TopicSchemaError):
        t.component_base(bad)
