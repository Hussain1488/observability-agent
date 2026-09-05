import os
from typing import Any, Iterator, Optional

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("GOOGLE_GENAI_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "*")

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda

from app.orchestration.schemas import RoutingResponse


class FakeChatModel(BaseChatModel):
    """Replays a scripted list of AIMessages, streaming text ones word by word."""

    script: list = []
    state: dict = {}
    route: str = "traces"
    routing_error: bool = False

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _next(self) -> AIMessage:
        i = self.state.setdefault("n", 0)
        self.state["n"] = i + 1
        return self.script[min(i, len(self.script) - 1)]

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        message = self._next()
        if message.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="", tool_calls=message.tool_calls, id=message.id
                )
            )
            return
        for word in message.content.split(" "):
            yield ChatGenerationChunk(message=AIMessageChunk(content=word + " "))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        def _route(_):
            if self.routing_error:
                raise RuntimeError("model refused to route")
            return RoutingResponse(routes=self.route, reasoning="test reasoning")

        return RunnableLambda(_route)


TOOL_CALL_MESSAGE = AIMessage(
    content="",
    id="ai-tool-call",
    tool_calls=[{"name": "get_trace", "args": {"service": "checkout"}, "id": "call-1"}],
)
FINAL_MESSAGE = AIMessage(content="The db.query span is the bottleneck.", id="ai-final")


@pytest.fixture(autouse=True)
def reset_graph_cache():
    """build_graph() is cached in a module global; stop it leaking between tests."""
    from app.orchestration import graph

    graph._graph = None
    yield
    graph._graph = None


@pytest.fixture
def fake_agents(monkeypatch):
    """Patch the graph's model factories so no test ever reaches OpenAI."""
    from app.orchestration import graph
    from app.tools.tools import get_tools

    orchestrator = FakeChatModel(script=[FINAL_MESSAGE], state={})

    def fake_get_agent(agent_name: str):
        tools = get_tools(["get_trace"]) if agent_name == "traces" else []
        script = [TOOL_CALL_MESSAGE, FINAL_MESSAGE] if tools else [FINAL_MESSAGE]
        return FakeChatModel(script=script, state={}), f"prompt:{agent_name}", tools

    monkeypatch.setattr(graph, "get_agent", fake_get_agent)
    monkeypatch.setattr(
        graph, "get_orchestrator_agent", lambda: (orchestrator, "prompt:orch", "support")
    )
    return orchestrator
