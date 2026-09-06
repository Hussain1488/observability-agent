from langsmith import Client
import json
import os
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
RECORDS_PATH = HERE / "langsmith_records.json"

# Load the project .env whatever directory this is run from.
load_dotenv(PROJECT_ROOT / ".env")
client = Client()

PROJECT = "ObservabilityAgent"


def _time_to_first_token(run) -> float | None:
    """Seconds until the first streamed token.

    start_time is normalised to UTC by the SDK but first_token_time is not, so
    it has to be made timezone-aware before the two can be subtracted.
    """
    first = run.first_token_time
    if first is None:
        return None
    if first.tzinfo is None:
        first = first.replace(tzinfo=run.start_time.tzinfo)
    return (first - run.start_time).total_seconds()

# The model name is only recorded on the LLM child runs, never on the root trace,
# so collect it separately and match it back to each trace by trace_id.
models_by_trace: dict[str, dict[str, dict]] = {}

for llm_run in client.list_runs(project_name=PROJECT, run_type="llm"):
    model = (llm_run.extra or {}).get("metadata", {}).get("ls_model_name")
    if not model:
        continue
    per_model = models_by_trace.setdefault(str(llm_run.trace_id), {})
    stats = per_model.setdefault(
        model,
        {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0},
    )
    stats["calls"] += 1
    stats["prompt_tokens"] += llm_run.prompt_tokens or 0
    stats["completion_tokens"] += llm_run.completion_tokens or 0
    stats["cost"] += llm_run.total_cost or 0

runs = client.list_runs(
    project_name=PROJECT,
    is_root=True,      # Only top-level traces (one per user request)
)

records = []

for run in runs:
    per_model = models_by_trace.get(str(run.trace_id), {})
    records.append({
        "trace_id": str(run.trace_id),
        "run_id": str(run.id),
        "name": run.name,
        "start_time": run.start_time.isoformat(),
        "inputs": run.inputs,
        "outputs": run.outputs,
        "metadata": run.extra,
        "error": run.error,

        # Performance
        "end_time": run.end_time.isoformat() if run.end_time else None,
        "latency_seconds": run.latency,
        "time_to_first_token": _time_to_first_token(run),

        # Which model(s) answered this trace, and what each one cost. Lets a
        # cheaper model be compared against a bigger one on the same questions.
        "models": sorted(per_model),
        "model_breakdown": per_model,

        # Cost: root runs roll up the tokens and cost of every child call.
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "total_tokens": run.total_tokens,
        "prompt_cost": run.prompt_cost,
        "completion_cost": run.completion_cost,
        "total_cost": run.total_cost,
    })

with RECORDS_PATH.open("w", encoding="utf-8") as f:
    json.dump(records, f, indent=2, default=str)

print(f"Wrote {len(records)} traces to {RECORDS_PATH}")