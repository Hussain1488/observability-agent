from app.core.agents import agent_names
from app.orchestration.graph import build_graph, get_graph, stream_chat
from tests.conftest import FINAL_MESSAGE, FakeChatModel


def _edges(compiled):
    return {(edge.source, edge.target) for edge in compiled.get_graph().edges}


def test_orchestrator_can_reach_every_agent(fake_agents):
    edges = _edges(build_graph())
    for name in agent_names():
        assert ("orchestrator", name) in edges


def test_tool_bearing_agent_loops_through_its_own_tools_node(fake_agents):
    compiled = build_graph()
    edges = _edges(compiled)

    assert "traces_tools" in compiled.get_graph().nodes
    assert ("traces", "traces_tools") in edges
    assert ("traces_tools", "traces") in edges
    assert ("traces", "__end__") in edges


def test_agent_without_tools_goes_straight_to_end(fake_agents):
    compiled = build_graph()

    assert "support_tools" not in compiled.get_graph().nodes
    assert ("support", "__end__") in _edges(compiled)


def test_graph_is_cached(fake_agents):
    assert get_graph() is get_graph()


async def test_stream_chat_emits_route_tool_and_token_events(fake_agents):
    events = [event async for event in stream_chat("why is checkout slow?", "t1")]
    kinds = [event["type"] for event in events]

    assert kinds[0] == "route"
    assert events[0]["agent"] == "traces"
    assert kinds.index("tool_call") < kinds.index("tool_result")
    assert kinds.index("tool_result") < kinds.index("token")


async def test_tool_events_carry_name_and_result(fake_agents):
    events = [event async for event in stream_chat("why is checkout slow?", "t1")]

    call = next(e for e in events if e["type"] == "tool_call")
    result = next(e for e in events if e["type"] == "tool_result")

    assert call["tool"] == "get_trace"
    assert call["args"] == {"service": "checkout"}
    assert result["tool"] == "get_trace"
    assert "db.query" in result["content"]


async def test_tokens_reassemble_into_the_answer(fake_agents):
    events = [event async for event in stream_chat("why is checkout slow?", "t1")]
    text = "".join(e["text"] for e in events if e["type"] == "token")

    assert text.strip() == FINAL_MESSAGE.content


async def test_agent_without_tools_emits_no_tool_events(fake_agents):
    fake_agents.route = "support"
    events = [event async for event in stream_chat("hello", "t1")]

    assert events[0] == {"type": "route", "agent": "support"}
    assert not any(e["type"].startswith("tool") for e in events)
    assert any(e["type"] == "token" for e in events)


async def test_orchestrator_falls_back_when_routing_fails(monkeypatch):
    from app.orchestration import graph
    from app.tools.tools import get_tools

    broken = FakeChatModel(script=[FINAL_MESSAGE], state={}, routing_error=True)
    monkeypatch.setattr(
        graph, "get_orchestrator_agent", lambda: (broken, "prompt:orch", "support")
    )
    monkeypatch.setattr(
        graph,
        "get_agent",
        lambda name: (FakeChatModel(script=[FINAL_MESSAGE], state={}), "p", get_tools([])),
    )

    events = [event async for event in stream_chat("anything", "t1")]

    assert events[0] == {"type": "route", "agent": "support"}
