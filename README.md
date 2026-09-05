# Observability Agent

An AI-powered observability assistant that helps engineers investigate distributed
systems. A router LLM classifies each question and dispatches it to one of six
specialised agents, each with its own system prompt and its own set of tools. Answers
stream back as plain text.

Built with FastAPI and LangGraph. See [DESIGN.md](DESIGN.md) for the reasoning behind the
architecture.

## How it works

```
POST /ask  →  Orchestrator (router LLM)  →  one specialist agent  →  streamed answer
                        │                            │
             classifies the intent          calls its own tools,
             returns route + reasoning      loops until it can answer
```

| Agent | Handles | Tools |
|---|---|---|
| `traces` | Latency, slow spans, where time goes | `get_trace`, `get_slow_spans` |
| `logs` | Errors, exceptions, log search | `search_logs`, `get_error_logs` |
| `metrics` | Error rate, throughput, CPU, memory | `get_metric`, `get_error_rate` |
| `docs` | Runbooks, how-to guides, onboarding | `search_docs`, `get_runbook` |
| `codes` | Source lookups, recent commits | `search_code`, `get_recent_commits` |
| `support` | Greetings, anything else (fallback) | — |

All tools return mock data. They describe one coherent incident: `checkout` is slow
because a `db.query` on `cart_items` is missing an index, while its `payments` dependency
times out with 504s after a commit removed the retry wrapper.

## Setup

### 1. Prerequisites

- Python 3.10+
- An OpenAI API key (Google Gemini is also supported per-agent in `agents.yaml`)

### 2. Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and fill in your key:

```env
OPENAI_API_KEY=sk-...
GOOGLE_GENAI_API_KEY=
ALLOWED_ORIGINS=*
```

### 5. Run

```bash
python -m uvicorn app.main:app --reload
```

The API is at `http://127.0.0.1:8000`.

> Use `python -m uvicorn` rather than bare `uvicorn`. If the project folder was ever
> renamed, the `.exe` launchers inside `.venv\Scripts\` still point at the old path and
> fail with *"Unable to create process"*. Going through `python -m` sidesteps them.

## API

### `POST /ask`

```json
{ "message": "Why is the checkout service slow?" }
```

Responds with `text/plain` streamed token by token as the agent generates it.

All requests share one conversation thread, so history accumulates across callers and is
lost on restart. The thread id is not part of the request body — see
[Conversation memory](DESIGN.md#9-conversation-memory) for why, and what production
would do instead.

Because the response is a stream, Swagger UI at `/docs` won't render it usefully — use
`curl -N` (the `-N` disables buffering so you see tokens arrive incrementally).

## Example requests

One per route, demonstrating six distinct query types.

**1. Traces** — routes to `traces`, calls `get_trace`

```bash
curl -N -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"message": "Why is the checkout service slow?"}'
```

**2. Logs** — routes to `logs`, calls `get_error_logs`

```bash
curl -N -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"message": "What errors is the payments service throwing?"}'
```

**3. Metrics** — routes to `metrics`, calls `get_error_rate`

```bash
curl -N -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the current error rate for checkout?"}'
```

**4. Docs** — routes to `docs`, calls `get_runbook`

```bash
curl -N -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"message": "Where is the runbook for a downstream timeout?"}'
```

**5. Code** — routes to `codes`, calls `get_recent_commits`

```bash
curl -N -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"message": "Which recent commits touched the payments service?"}'
```

**6. Support (fallback)** — routes to `support`, no tools

```bash
curl -N -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"message": "Hi, what can you help me with?"}'
```

## Tests

```bash
python -m pytest
```

The suite never calls an LLM provider — a fake chat model is patched over the model
factories, so tests are free and run offline. It covers agent config integrity, graph
topology, streaming event order, router fallback, and the API endpoint.

## Evaluation

`evals/dataset.yaml` holds 25 questions spanning all six routes, each with an expected
route, expected tools, a reference answer, and key facts drawn from the mock data.

```bash
python -m evals.run_eval
```

This calls the real LLM (~65 `gpt-4o-mini` calls) and writes `evals/report.md`, scoring
three things:

| Metric | What it measures |
| --- | --- |
| Routing accuracy | Did the orchestrator pick the right agent? (exact match) |
| Tool selection | Did the agent call one of the expected tools? |
| Answer grounding | Does the answer contain a key fact from the tool output? |

The report includes a per-route accuracy breakdown, a table of misroutes, and for every
question the reference answer next to the generated one.

### Run history and comparison

Every run writes three things:

| Path | Contents |
| --- | --- |
| `evals/report.md` | Human-readable report for the latest run |
| `evals/report.json` | Machine-readable latest run |
| `evals/history/<timestamp>.json` | Permanent archive of that run |

Nothing is ever overwritten in `history/`, so accuracy over time is preserved:

```bash
python -m evals.run_eval --history
```

```
| Run              | Routing      | Tools        | Grounding    | Fully correct |
| 2026-09-03 10:00 | 22/25 (88%)  | 21/25 (84%)  | 18/22 (82%)  | 17/25 (68%)   |
| 2026-09-04 10:00 | 24/25 (96%)  | 24/25 (96%)  | 20/22 (91%)  | 22/25 (88%)   |
```

After the first run, each subsequent run also prints what changed — including
per-question regressions and improvements, which aggregate scores can hide when they
offset each other:

```
Routing accuracy   22/25 -> 24/25  (+2)
Fully correct      19/25 -> 22/25  (+3)

Regressions (1):
  Q7   Search the logs for 504 timeout errors.   route: logs -> metrics
```

To re-print that comparison without spending anything:

```bash
python -m evals.run_eval --compare
```

### Tracing with LangSmith

Set these in `.env` and every request — including eval runs — is traced with per-node
latency, token counts, and computed cost:

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=ObservabilityAgent
```

Send eval traces to their own project so they don't mix with app traffic:

```powershell
$env:LANGSMITH_PROJECT="ObservabilityAgent-evals"; python -m evals.run_eval
```

A shell variable takes precedence over `.env`, since `load_dotenv()` doesn't override
variables already set in the environment.

## Adding an agent

No Python required. Add an entry to `app/core/agents.yaml`:

```yaml
  deploys:
    description: Deployment history and rollout status.
    system_prompt: >
      You are the Deploys Agent...
    provider: chatgpt
    model: gpt-4o-mini
    temperature: 0.0
    tools: [get_recent_commits]
```

The graph builds itself from the file, and the router's `Literal` in
`app/orchestration/schemas.py` needs the new route name added.

## Project structure

```
app/
  main.py                    FastAPI app and CORS
  api/
    chat.py                  POST /ask
    schemas.py               request/response models
  core/
    agents.py                YAML loading, model construction
    agents.yaml              agent definitions (prompts, models, tools)
    config.py                settings and API keys
  orchestration/
    graph.py                 router node, agent nodes, streaming
    schemas.py               RoutingResponse (route + reasoning)
  tools/
    tools.py                 mock observability tools + registry
tests/                       offline test suite
```
