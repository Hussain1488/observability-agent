"""Join LangSmith cost/latency against eval accuracy, grouped by run.

Reads the two files that already exist:

  evals/langsmith_records.json - written by langsmith_report_download.py (cost, speed, models)
  evals/history/*.json    - written by evals.run_eval               (accuracy)

and prints one row per run so a cheaper model can be compared against a bigger
one on the same questions.

Usage:
    python evals/compare_models.py
    python evals/compare_models.py --csv comparison.csv

Nothing in app/ or evals/ is imported or modified.
"""

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECORDS_PATH = HERE / "langsmith_records.json"
HISTORY_DIR = HERE / "history"

# stream_chat() is called with thread_id=f"eval-{id}", so this is what marks a
# trace as belonging to an evaluation run rather than a real user request.
EVAL_THREAD = re.compile(r"^eval-(\d+)$")


def _meta(record: dict) -> dict:
    """The inner metadata dict, which is nested one level inside run.extra."""
    return (record.get("metadata") or {}).get("metadata") or {}


def _float(value) -> float | None:
    """Costs arrive as strings because Decimal is not valid JSON."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


def group_key(record: dict) -> str:
    """Prefer an explicit run label; fall back to the git revision LangSmith adds."""
    meta = _meta(record)
    for key in ("LANGSMITH_RUN_LABEL", "LANGSMITH_EVAL_LABEL", "LANGCHAIN_EXPERIMENT"):
        if meta.get(key):
            return str(meta[key])
    return str(meta.get("revision_id") or "unlabelled")


def load_trace_groups(path: Path) -> dict[str, dict]:
    """Group eval traces by run label, keeping one entry per question id."""
    records = json.loads(path.read_text(encoding="utf-8"))
    groups: dict[str, dict] = {}

    for record in records:
        match = EVAL_THREAD.match(str(_meta(record).get("thread_id") or ""))
        if not match:
            continue  # a real user request, not an eval question

        group = groups.setdefault(
            group_key(record),
            {"questions": {}, "models": set(), "latest": None},
        )

        started = _parse_time(record.get("start_time"))
        if started and (group["latest"] is None or started > group["latest"]):
            group["latest"] = started

        group["models"].update(record.get("models") or [])

        # Re-running one question overwrites the earlier attempt in the same group.
        group["questions"][int(match.group(1))] = {
            "cost": _float(record.get("total_cost")),
            "latency": _float(record.get("latency_seconds")),
            "tokens": record.get("total_tokens"),
        }

    return groups


def load_eval_runs(directory: Path) -> list[dict]:
    if not directory.exists():
        return []
    runs = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["_file"] = path.name
        payload["_time"] = _parse_time(payload.get("generated_at"))
        runs.append(payload)
    return runs


def match_eval_runs(
    groups: dict[str, dict], eval_runs: list[dict]
) -> dict[str, dict | None]:
    """Pair each trace group with the eval run that produced it.

    Preferred join: the run label. Both sides record it -- LangSmith copies
    LANGSMITH_RUN_LABEL into every trace, and run_eval.py writes the same value
    into its archive -- so the match is exact.

    Fallback for archives written before that field existed: pair whatever is
    left over by running order. That is only sound when the two sides have the
    same number of entries, so it warns when they do not.
    """
    matches: dict[str, dict | None] = {label: None for label in groups}
    claimed: set[str] = set()

    by_label: dict[str, dict] = {}
    for run in eval_runs:
        label = run.get("run_label")
        if label:
            by_label.setdefault(str(label), run)

    for label in groups:
        run = by_label.get(label)
        if run is not None:
            matches[label] = run
            claimed.add(run["_file"])

    leftover_runs = sorted(
        (r for r in eval_runs if r["_file"] not in claimed and r["_time"]),
        key=lambda r: r["_time"],
    )
    leftover_groups = sorted(
        (
            label
            for label, g in groups.items()
            if matches[label] is None and g["latest"]
        ),
        key=lambda label: groups[label]["latest"],
    )

    if leftover_groups and len(leftover_groups) != len(leftover_runs):
        # Rows matched on a label above are exact and unaffected by this; only
        # the leftovers are unresolvable, so they are left blank rather than
        # guessed at.
        print(
            f"Left unmatched: {', '.join(leftover_groups)}. "
            f"{len(leftover_groups)} trace group(s) carry no run label but "
            f"{len(leftover_runs)} eval archive(s) are spare, and order pairing "
            "needs equal numbers. Rows matched by label are unaffected."
        )
        return matches

    for label, run in zip(leftover_groups, leftover_runs):
        matches[label] = run

    return matches


def summarise(group: dict, eval_run: dict | None) -> dict:
    questions = group["questions"]
    costs = [q["cost"] for q in questions.values() if q["cost"] is not None]
    latencies = [q["latency"] for q in questions.values() if q["latency"] is not None]

    row = {
        "questions": len(questions),
        "models": ", ".join(sorted(group["models"])) or "unknown",
        "total_cost": sum(costs) if costs else None,
        "avg_cost": sum(costs) / len(costs) if costs else None,
        "avg_latency": sum(latencies) / len(latencies) if latencies else None,
        "accuracy": None,
        "routing": None,
        "eval_file": None,
        "matched_by": None,
    }

    if eval_run:
        summary = eval_run["summary"]
        row["accuracy"] = summary["fully_correct"] / summary["total"]
        row["routing"] = summary["routing"] / summary["total"]
        row["eval_file"] = eval_run["_file"]
        row["matched_by"] = "label" if eval_run.get("run_label") else "order"

    return row


def _fmt(value, spec: str, missing: str = "n/a") -> str:
    return missing if value is None else format(value, spec)


def print_table(rows: dict[str, dict]) -> None:
    header = (
        f"{'Run':<28} {'Questions':>9} {'Accuracy':>9} {'Routing':>8} "
        f"{'Total $':>9} {'$/question':>11} {'Latency':>8}  Models"
    )
    print(header)
    print("-" * (len(header) + 12))

    for label, row in sorted(rows.items()):
        print(
            f"{label[:28]:<28} "
            f"{row['questions']:>9} "
            f"{_fmt(row['accuracy'], '.1%'):>9} "
            f"{_fmt(row['routing'], '.1%'):>8} "
            f"{_fmt(row['total_cost'], '.4f'):>9} "
            f"{_fmt(row['avg_cost'], '.6f'):>11} "
            f"{_fmt(row['avg_latency'], '.2f'):>8}  "
            f"{row['models']}"
        )

    stale = [r for r in rows.values() if r["total_cost"] is None]
    if stale:
        print(
            "\nSome runs show no cost. Either langsmith_records.json predates the "
            "cost fields (re-run evals/langsmith_report_download.py), or LangSmith has "
            "no pricing for that model (add it under Settings -> Models)."
        )

    unmatched = [label for label, r in rows.items() if r["accuracy"] is None]
    if unmatched:
        print(
            "\nNo accuracy for: "
            + ", ".join(unmatched)
            + " (fewer eval archives than trace groups)."
        )

    unlabelled = [label for label, r in rows.items() if r["matched_by"] == "order"]
    if unlabelled:
        print(
            "\nPaired by running order (no run label): "
            + ", ".join(unlabelled)
            + ". Set LANGSMITH_RUN_LABEL when running the evaluation to make "
            "this an exact match."
        )


def write_csv(rows: dict[str, dict], path: Path) -> None:
    columns = [
        "run",
        "questions",
        "models",
        "accuracy",
        "routing",
        "total_cost",
        "avg_cost",
        "avg_latency",
        "eval_file",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for label, row in sorted(rows.items()):
            writer.writerow({"run": label, **{c: row.get(c) for c in columns[1:]}})
    print(f"\nWritten to {path}")


def main(csv_path: Path | None) -> None:
    if not RECORDS_PATH.exists():
        print(f"{RECORDS_PATH} not found. Run evals/langsmith_report_download.py first.")
        return

    groups = load_trace_groups(RECORDS_PATH)
    if not groups:
        print(
            "No evaluation traces found. Traces are matched on a thread_id of "
            "'eval-<number>', which evals/run_eval.py sets. Run the evaluation, "
            "then download the records again."
        )
        return

    eval_runs = load_eval_runs(HISTORY_DIR)
    if not eval_runs:
        print("No eval history found; showing cost and speed only.\n")

    matches = match_eval_runs(groups, eval_runs)
    rows = {
        label: summarise(group, matches[label]) for label, group in groups.items()
    }

    print_table(rows)

    if csv_path:
        write_csv(rows, csv_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare accuracy against cost across evaluation runs."
    )
    parser.add_argument("--csv", type=Path, help="Also write the table to a CSV file.")
    main(parser.parse_args().csv)
