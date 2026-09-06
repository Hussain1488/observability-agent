"""Run the evaluation dataset against the live agent and write a markdown report.

Usage:
    python -m evals.run_eval

Requires a real OPENAI_API_KEY: every question costs one routing call plus one or two
agent calls (~65 gpt-4o-mini calls for the full set).
"""

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from app.orchestration.graph import stream_chat

load_dotenv()

DATASET_PATH = Path(__file__).parent / "dataset.yaml"
REPORT_PATH = Path(__file__).parent / "report.md"
REPORT_JSON_PATH = Path(__file__).parent / "report.json"
HISTORY_DIR = Path(__file__).parent / "history"


@dataclass
class Result:
    id: int
    question: str
    expected_route: str
    expected_tools: list[str]
    expected_answer: str
    key_facts: list[str]
    actual_route: str = ""
    called_tools: list[str] = field(default_factory=list)
    answer: str = ""
    error: str = ""

    @property
    def route_ok(self) -> bool:
        return self.actual_route == self.expected_route

    @property
    def tools_ok(self) -> bool:
        if not self.expected_tools:
            return not self.called_tools
        return any(tool in self.called_tools for tool in self.expected_tools)

    @property
    def grounded(self) -> bool:
        answer = self.answer.lower()
        return any(fact.lower() in answer for fact in self.key_facts)

    @property
    def scorable_facts(self) -> bool:
        return bool(self.key_facts)

    @property
    def fully_correct(self) -> bool:
        return (
            self.route_ok
            and self.tools_ok
            and (self.grounded or not self.scorable_facts)
            and not self.error
        )


async def run_question(item: dict) -> Result:
    result = Result(
        id=item["id"],
        question=item["question"],
        expected_route=item["expected_route"],
        expected_tools=item.get("expected_tools", []),
        expected_answer=item["expected_answer"].strip(),
        key_facts=item.get("key_facts", []),
    )

    # A unique thread per question: the shared default would leak history between them
    # and change how later questions are routed.
    thread_id = f"eval-{item['id']}"
    tokens: list[str] = []

    try:
        async for event in stream_chat(result.question, thread_id):
            match event["type"]:
                case "route":
                    result.actual_route = event["agent"]
                case "tool_call":
                    result.called_tools.append(event["tool"])
                case "token":
                    tokens.append(event["text"])
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    result.answer = "".join(tokens).strip()
    return result


def _pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "n/a"
    return f"{numerator}/{denominator} ({numerator / denominator * 100:.1f}%)"


def summarise(results: list[Result]) -> dict[str, int]:
    factual = [r for r in results if r.scorable_facts]
    return {
        "total": len(results),
        "routing": sum(r.route_ok for r in results),
        "tools": sum(r.tools_ok for r in results),
        "grounded": sum(r.grounded for r in factual),
        "grounded_total": len(factual),
        "fully_correct": sum(r.fully_correct for r in results),
    }


def write_json(results: list[Result], path: Path) -> dict:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        # Same label LangSmith stamps on the traces, so a report can be joined
        # to its traces exactly instead of by guessing from timestamps.
        "run_label": os.getenv("LANGSMITH_RUN_LABEL"),
        "summary": summarise(results),
        "results": [
            {
                "id": r.id,
                "question": r.question,
                "expected_route": r.expected_route,
                "actual_route": r.actual_route,
                "route_ok": r.route_ok,
                "expected_tools": r.expected_tools,
                "called_tools": r.called_tools,
                "tools_ok": r.tools_ok,
                "grounded": r.grounded,
                "fully_correct": r.fully_correct,
                "answer": r.answer,
                "error": r.error,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def history_files() -> list[Path]:
    """Archived runs, oldest first. Filenames sort chronologically by construction."""
    if not HISTORY_DIR.exists():
        return []
    return sorted(HISTORY_DIR.glob("*.json"))


def build_trend(runs: list[dict]) -> str:
    lines = [
        "Evaluation history (oldest first)",
        "",
        "| Run | Routing | Tools | Grounding | Fully correct |",
        "| --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        s = run["summary"]
        lines.append(
            f"| {run['generated_at'][:16].replace('T', ' ')} "
            f"| {_pct(s['routing'], s['total'])} "
            f"| {_pct(s['tools'], s['total'])} "
            f"| {_pct(s['grounded'], s['grounded_total'])} "
            f"| {_pct(s['fully_correct'], s['total'])} |"
        )
    return "\n".join(lines)


def build_comparison(previous: dict, current: dict) -> str:
    lines = [f"Comparison vs previous run ({previous['generated_at']})", ""]
    before, after = previous["summary"], current["summary"]

    for label, key, total_key in [
        ("Routing accuracy", "routing", "total"),
        ("Tool selection", "tools", "total"),
        ("Answer grounding", "grounded", "grounded_total"),
        ("Fully correct", "fully_correct", "total"),
    ]:
        delta = after[key] - before[key]
        change = f"{delta:+d}" if delta else "no change"
        lines.append(
            f"  {label:<18} {before[key]}/{before[total_key]} -> "
            f"{after[key]}/{after[total_key]}  ({change})"
        )

    was = {r["id"]: r for r in previous["results"]}
    regressions, improvements = [], []
    for now in current["results"]:
        then = was.get(now["id"])
        if then is None:
            continue
        if then["fully_correct"] and not now["fully_correct"]:
            regressions.append((then, now))
        elif not then["fully_correct"] and now["fully_correct"]:
            improvements.append((then, now))

    for title, items in [("Regressions", regressions), ("Improvements", improvements)]:
        lines += ["", f"{title} ({len(items)}):"]
        if not items:
            lines.append("  none")
            continue
        for then, now in items:
            detail = ""
            if then["actual_route"] != now["actual_route"]:
                detail = f"  route: {then['actual_route']} -> {now['actual_route']}"
            lines.append(f"  Q{now['id']:<3} {now['question'][:55]}{detail}")

    return "\n".join(lines)


def build_report(results: list[Result]) -> str:
    counts = summarise(results)
    total = counts["total"]
    routed = counts["routing"]
    tools_correct = counts["tools"]
    grounded = counts["grounded"]
    factual_total = counts["grounded_total"]
    overall = counts["fully_correct"]

    lines = [
        "# Evaluation Report",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M}  ",
        f"Questions: {total}",
        "",
        "## Summary",
        "",
        "| Metric | Score |",
        "| --- | --- |",
        f"| Routing accuracy | {_pct(routed, total)} |",
        f"| Tool selection | {_pct(tools_correct, total)} |",
        f"| Answer grounding | {_pct(grounded, factual_total)} |",
        f"| **Fully correct** | **{_pct(overall, total)}** |",
        "",
        "*Routing* is an exact match on the chosen agent. *Tool selection* counts a hit "
        "when the agent called one of the expected tools (or none, where none were "
        "expected). *Answer grounding* checks the answer contains at least one key fact "
        "from the mock data, and is only scored for questions that have key facts.",
        "",
        "## Routing accuracy by route",
        "",
        "| Route | Correct | Total | Accuracy |",
        "| --- | --- | --- | --- |",
    ]

    for route in sorted({r.expected_route for r in results}):
        subset = [r for r in results if r.expected_route == route]
        correct = sum(r.route_ok for r in subset)
        pct = f"{correct / len(subset) * 100:.0f}%"
        lines.append(f"| {route} | {correct} | {len(subset)} | {pct} |")

    misroutes = [r for r in results if not r.route_ok]
    lines += ["", "## Misroutes", ""]
    if misroutes:
        lines += ["| # | Question | Expected | Actual |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {r.id} | {r.question} | {r.expected_route} | {r.actual_route or '—'} |"
            for r in misroutes
        ]
    else:
        lines.append("None — every question routed correctly.")

    errors = [r for r in results if r.error]
    if errors:
        lines += ["", "## Errors", ""]
        lines += [f"- **Q{r.id}**: `{r.error}`" for r in errors]

    lines += ["", "## Detailed results", ""]
    for r in results:
        status = "PASS" if r.fully_correct else "FAIL"
        lines += [
            f"### Q{r.id} — {status}",
            "",
            f"**Question:** {r.question}",
            "",
            f"- Route: expected `{r.expected_route}`, got `{r.actual_route or '—'}` "
            f"{'✅' if r.route_ok else '❌'}",
            f"- Tools: expected `{r.expected_tools or 'none'}`, called "
            f"`{r.called_tools or 'none'}` {'✅' if r.tools_ok else '❌'}",
        ]
        if r.scorable_facts:
            found = [f for f in r.key_facts if f.lower() in r.answer.lower()]
            lines.append(
                f"- Grounding: found `{found or 'none'}` of `{r.key_facts}` "
                f"{'✅' if r.grounded else '❌'}"
            )
        lines += [
            "",
            f"**Correct answer:** {r.expected_answer}",
            "",
            f"**Generated answer:** {r.answer or '_(empty)_'}",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


async def main(compare_only: bool, show_history: bool) -> None:
    archived = history_files()

    if show_history:
        runs = [load_json(path) for path in archived]
        print(build_trend(runs) if runs else "No runs recorded yet.")
        return

    if compare_only:
        if len(archived) < 2:
            print("Need two completed runs before results can be compared.")
            return
        print(build_comparison(load_json(archived[-2]), load_json(archived[-1])))
        return

    previous = load_json(archived[-1]) if archived else None
    logging.disable(logging.INFO)
    dataset = yaml.safe_load(DATASET_PATH.read_text(encoding="utf-8"))["questions"]

    results: list[Result] = []
    for item in dataset:
        result = await run_question(item)
        results.append(result)
        mark = "PASS" if result.fully_correct else "FAIL"
        print(f"[{result.id:>2}/{len(dataset)}] {mark}  {result.question[:60]}")

    REPORT_PATH.write_text(build_report(results), encoding="utf-8")
    current = write_json(results, REPORT_JSON_PATH)

    HISTORY_DIR.mkdir(exist_ok=True)
    archive = HISTORY_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    write_json(results, archive)

    counts = summarise(results)
    print(f"\nRouting accuracy: {_pct(counts['routing'], counts['total'])}")
    print(f"Fully correct:    {_pct(counts['fully_correct'], counts['total'])}")
    print(f"Report written to {REPORT_PATH} (archived as {archive.name})")

    if previous is not None:
        print()
        print(build_comparison(previous, current))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the agent evaluation dataset.")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare the last two runs without calling the LLM.",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Show accuracy across all archived runs.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.compare, args.history))
