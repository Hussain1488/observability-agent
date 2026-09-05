import pytest

from app.tools.tools import TOOL_REGISTRY, get_tools


def test_get_tools_returns_requested_tools_in_order():
    tools = get_tools(["get_metric", "get_trace"])
    assert [tool.name for tool in tools] == ["get_metric", "get_trace"]


def test_get_tools_empty_list():
    assert get_tools([]) == []


def test_unknown_tool_name_raises():
    with pytest.raises(KeyError, match="search_everything"):
        get_tools(["get_trace", "search_everything"])


def test_registry_keys_match_tool_names():
    assert all(name == tool.name for name, tool in TOOL_REGISTRY.items())


def test_tools_are_invocable():
    result = TOOL_REGISTRY["get_trace"].invoke({"service": "checkout"})
    assert "db.query" in result
