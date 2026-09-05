from collections.abc import AsyncIterator, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
import logging

from app.core.agents import agent_names, get_agent, get_orchestrator_agent
from app.orchestration.schemas import RoutingResponse

logger = logging.getLogger(__name__)

class GraphState(MessagesState):
    selected_agent: str


def _add_agent_nodes(builder: StateGraph, agent_name: str) -> None:
    model, system_prompt, tools = get_agent(agent_name)
    system_message = SystemMessage(content=system_prompt)

    if tools:
        model = model.bind_tools(tools)

    async def agent_node(state: GraphState):
        response = await model.ainvoke([system_message, *state["messages"]])
        return {"messages": [response]}

    builder.add_node(agent_name, agent_node)

    if not tools:
        builder.add_edge(agent_name, END)
        return

    tools_name = f"{agent_name}_tools"
    builder.add_node(tools_name, ToolNode(tools))
    builder.add_conditional_edges(
        agent_name, tools_condition, {"tools": tools_name, END: END}
    )
    builder.add_edge(tools_name, agent_name)


def _build_orchestrator_node() -> Callable:
    model, system_prompt, fallback_route = get_orchestrator_agent()
    router = model.with_structured_output(RoutingResponse)
    system_message = SystemMessage(content=system_prompt)

    async def orchestrator(state: GraphState):
        question = state["messages"][-1]
        logger.info("Routing question: %s", question.content)
        try:
            decision = await router.ainvoke([system_message, question])
            logger.info("Routed to '%s': %s", decision.routes, decision.reasoning)
            return {"selected_agent": decision.routes}
        except Exception:
            logger.exception("Routing failed, falling back to '%s'", fallback_route)
            return {"selected_agent": fallback_route}

    return orchestrator


def build_graph() -> CompiledStateGraph:
    names = agent_names()
    builder = StateGraph(GraphState)

    builder.add_node("orchestrator", _build_orchestrator_node())
    for name in names:
        _add_agent_nodes(builder, name)

    builder.add_edge(START, "orchestrator")
    builder.add_conditional_edges(
        "orchestrator", lambda state: state["selected_agent"], names
    )

    logger.info("Building graph with agents: %s", names)
    return builder.compile(checkpointer=InMemorySaver())


_graph = None


def get_graph() -> CompiledStateGraph:
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def stream_chat(message: str, thread_id: str= "10101010") ->AsyncIterator[dict]:
    """Yield routing, token, and tool events for one user message."""
    graph = get_graph()
    agents = set(agent_names())

    async for mode, payload in graph.astream(
        {"messages": [HumanMessage(content=message)]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            chunk, metadata = payload
            if metadata.get("langgraph_node") in agents and chunk.text:
                yield {"type": "token", "text": chunk.text}
            continue

        for node_name, update in payload.items():
            if node_name == "orchestrator":
                yield {"type": "route", "agent": update["selected_agent"]}
            elif node_name.endswith("_tools"):
                for tool_message in update["messages"]:
                    logger.debug("Tool '%s' returned: %s", tool_message.name, tool_message.content)
                    yield {
                        "type": "tool_result",
                        "tool": tool_message.name,
                        "content": tool_message.content,
                    }
            elif node_name in agents:
                for tool_call in getattr(update["messages"][-1], "tool_calls", []):
                    logger.info("Agent '%s' calling tool %s(%s)", node_name, tool_call["name"], tool_call["args"])
                    yield {
                        "type": "tool_call",
                        "tool": tool_call["name"],
                        "args": tool_call["args"],
                    }

async def stream_tokens(message: str, thread_id: str = "10101010") ->AsyncIterator[str]:
    async for event in stream_chat(message, thread_id):
        if event["type"] == "token":
            yield event["text"]