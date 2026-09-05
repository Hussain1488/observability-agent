import pytest

from app.core.agents import agent_names, agents_config, get_agent, get_orchestrator_agent
from app.tools.tools import TOOL_REGISTRY


def test_every_agent_in_yaml_builds():
    """Catches typos in agents.yaml: bad provider, missing model, unknown tool name."""
    for name in agent_names():
        model, system_prompt, tools = get_agent(name)
        assert model is not None
        assert system_prompt.strip()
        assert all(tool.name in TOOL_REGISTRY for tool in tools)


def test_agent_tools_match_yaml():
    for name, config in agents_config["agents"].items():
        _, _, tools = get_agent(name)
        assert [tool.name for tool in tools] == config.get("tools", [])


def test_unknown_agent_raises():
    with pytest.raises(ValueError, match="not found"):
        get_agent("does_not_exist")


def test_support_agent_has_no_tools():
    _, _, tools = get_agent("support")
    assert tools == []


def test_orchestrator_fallback_route_is_a_real_agent():
    _, system_prompt, fallback_route = get_orchestrator_agent()
    assert system_prompt.strip()
    assert fallback_route in agent_names()


def test_unsupported_provider_raises():
    from app.core.agents import _build_model

    with pytest.raises(ValueError, match="Unsupported provider"):
        _build_model({"provider": "llama.cpp", "model": "x"})
