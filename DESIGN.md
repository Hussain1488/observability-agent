# Design Decisions

This document explains *why* the observability agent is built the way it is. For setup
and usage, see [README.md](README.md).

---

## Architecture at a glance

```
POST /ask
   │
   ▼
┌──────────────┐   structured output    ┌─────────────────────────────┐
│ Orchestrator │ ─────────────────────► │ RoutingResponse             │
│  (router LLM)│                        │  routes: traces|logs|...    │
└──────────────┘                        │  reasoning: str             │
   │                                    └─────────────────────────────┘
   │ conditional edge on `selected_agent`
   ▼
┌─────────┬────────┬─────────┬────────┬────────┬─────────┐
│ traces  │  logs  │ metrics │  docs  │ codes  │ support │
└────┬────┴───┬────┴────┬────┴───┬────┴───┬────┴─────────┘
     │        │         │        │        │         (no tools)
     ▼        ▼         ▼        ▼        ▼              │
  ┌───────────────────────────────────────┐              │
  │  <agent>_tools  (ToolNode, per agent) │              │
  └───────────────┬───────────────────────┘              │
                  │ loops back to its agent              │
                  └──────────────────────────────────────┴──► END
                                                              (streamed)
```

Each specialist is a full tool-calling loop, not a single shot: the agent may call a
tool, read the result, and call another before answering.

---

## 1. LangGraph for orchestration

**Decision:** Use LangGraph's `StateGraph` rather than hand-rolling an agent loop or
adopting a heavier framework.

**Why:** The core requirement is conditional routing plus a tool-calling loop. LangGraph
expresses both declaratively — `add_conditional_edges` for routing, and an
agent ↔ tools cycle for the ReAct pattern — and gives token streaming and checkpointed
memory without extra code. Writing the loop by hand would mean re-implementing tool
dispatch, message accumulation, and stream plumbing.

**Rejected alternative:** `create_react_agent` from `langgraph.prebuilt` would collapse
each agent to one line, but it is opinionated about prompt and state shape. Building the
nodes explicitly lets each agent draw its system prompt and tool list straight from YAML.

---

## 2. Configuration-driven agents (`agents.yaml`)

**Decision:** Agents are data, not code. Every specialist is a YAML entry with a
`description`, `system_prompt`, `provider`, `model`, `temperature`, and `tools` list.

**Why:** Adding a seventh agent requires no Python — one YAML block and the graph builds
itself from `agent_names()`. Prompts are the part of an LLM system that changes most
often, and keeping them out of source makes them reviewable by people who don't read
Python.

**Consequence:** YAML typos become runtime errors rather than import errors, so the test
suite builds *every* agent in the file to catch a bad provider, missing model, or unknown
tool name before deploy.

---

## 3. A router LLM with structured output

**Decision:** A dedicated orchestrator LLM classifies the request and returns a
`RoutingResponse` (route + reasoning) via `with_structured_output()`.

**Why structured output over prompt-and-parse:** The route must be one of six exact
strings. A `Literal` type on a Pydantic model makes the provider enforce the enum, which
removes a whole class of "model replied `Traces Agent` instead of `traces`" failures. The
earlier `PydanticOutputParser` approach put format instructions in the prompt and hoped —
this makes it a schema constraint instead.

**Why a separate call rather than one agent with all ten tools:** The challenge asks for
a router; separating classification from answering also keeps each specialist's prompt
short and focused.

**The tradeoff, stated plainly:** this costs one extra LLM call of latency per request,
and it means a specialist can only see its own two tools. A genuinely cross-cutting
question ("why is checkout slow?" — which touches traces, logs, metrics *and* recent
commits) gets answered by one specialist working from partial evidence. See
[Known limitations](#known-limitations).

---

## 4. Per-agent tool nodes

**Decision:** Each tool-bearing agent gets its own `ToolNode`, named `<agent>_tools`,
wired `agent → tools_condition → <agent>_tools → agent`.

**Why not one shared tool node:** A shared node would expose every tool to every agent,
which defeats the point of specialisation and lets the logs agent call `get_trace`. Giving
each agent a private node means the tool boundary is enforced by graph topology, not by
prompt discipline.

Agents with no tools (`support`) skip the cycle and edge straight to `END`.

---

## 5. Two streaming layers

**Decision:** `stream_chat()` yields structured events; `stream_tokens()` filters those
down to plain text, and the API returns text by default.

```
stream_chat  →  {"type": "route",       "agent": "traces"}
                {"type": "tool_call",   "tool": "get_trace", "args": {...}}
                {"type": "tool_result", "tool": "get_trace", "content": "..."}
                {"type": "token",       "text": "The "}

stream_tokens → "The "   (tokens only)
```

**Why both:** The endpoint contract is streamable text, so that is the default. But the
routing decision and tool activity are the interesting part of an observability
assistant — a future UI wants to show "consulting the traces agent… calling get_trace…"
while the answer is still being generated. Keeping the structured layer underneath means
that UI needs no changes to the graph.

**Implementation note:** the agent nodes call `await model.ainvoke(...)`, not `astream`,
yet tokens still stream. LangGraph attaches a streaming callback handler when
`stream_mode` includes `"messages"`, which makes the underlying model stream internally.
Accumulating chunks by hand would be redundant.

---

## 6. Mock tools

**Decision:** All ten tools return hardcoded strings from `app/tools/tools.py`. No network
calls.

**Why:** The challenge permits mock data, and it keeps LLM/infrastructure cost at zero for
everything except the model calls themselves. More importantly, the mock data tells **one
coherent incident story** — the `checkout` service is slow because a `db.query` on
`cart_items` lacks an index, while a downstream `payments` dependency times out with 504s
after a commit removed its retry wrapper. That means cross-referencing agents produces a
consistent narrative instead of unrelated noise, which makes the routing behaviour
demonstrable.

A `TOOL_REGISTRY` maps names to tools so YAML can reference them by string, and
`get_tools()` raises on unknown names rather than silently returning fewer tools.

---

## 7. Cost control

**Decision:** `gpt-4o-mini` at `temperature: 0` for every agent including the router.

**Why:** The challenge explicitly asks to minimise spend. `gpt-4o-mini` is sufficient for
classification and for summarising mock tool output, and zero temperature makes routing
reproducible — the same question routes the same way every time, which also makes the
behaviour testable.

The graph is built once and cached (`get_graph()`), so model clients are constructed at
startup rather than per request.

---

## 8. Testing without spending money

**Decision:** The suite never contacts a provider. A `FakeChatModel` in `tests/conftest.py`
replays scripted messages and streams them word by word, patched over `get_agent` and
`get_orchestrator_agent`.

**Why:** Tests that cost money and need network access don't get run. The fake implements
`bind_tools`, `with_structured_output`, and `_stream`, which is enough to exercise the
real graph — routing, the tool loop, and token streaming all run genuine LangGraph code.

Coverage focuses on what actually breaks: every agent in the YAML builds; the graph
topology is correct; `stream_chat` emits events in the right order; the router falls back
to `support` when classification fails; the endpoint streams and rejects bad input.

---

## Known limitations

These are deliberate scope choices, not oversights.

1. **Specialists can't collaborate.** The router picks exactly one agent, so a question
   spanning traces *and* commits gets a partial answer. A supervisor pattern — exposing
   specialists as tools to a coordinator that can consult several and synthesise — would
   fix this while keeping the same visible architecture. This is the first thing I would
   change with more time.
2. **Memory is in-process.** `InMemorySaver` does not survive a restart and is not shared
   across workers. Conversations are keyed by `thread_id`; a production deployment needs a
   Redis or Postgres checkpointer.
3. **Routing latency.** Every request pays one classification call before any answer
   token appears.
4. **No streaming error contract.** Once `200 OK` and the first byte are sent, a mid-stream
   failure cannot change the status code. Errors currently surface as a truncated
   response rather than a structured error frame.
5. **Tools are mocks.** Real backends (Tempo, Loki, Prometheus) would introduce auth,
   pagination, and partial-failure handling that the current tool signatures don't model.
