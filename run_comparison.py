"""Run the evaluation once per model, then build the accuracy-vs-cost table.

For each model it rewrites the provider/model lines in app/core/agents.yaml,
runs the existing evaluation, and puts the original file back afterwards. The
file is restored even if a run fails or you press Ctrl-C.

Each run is labelled through LANGSMITH_RUN_LABEL, which LangSmith copies into
the metadata of every trace, so the runs can be told apart later.

Usage:
    python run_comparison.py                 # all models below
    python run_comparison.py --only gpt-4o-mini
    python run_comparison.py --dry-run       # show the plan, spend nothing
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

AGENTS_PATH = Path("app/core/agents.yaml")

# (label, provider, model). Provider must match _build_model() in app/core/agents.py.
MODELS = [
    ("gpt-4o-mini", "chatgpt", "gpt-4o-mini"),
    ("gpt-4.1-nano", "chatgpt", "gpt-4.1-nano"),
    ("gemini-3.5-flash-lite-paid", "GoogleGenAI", "gemini-3.5-flash-lite"),
    ("gemini-3.1-flash-lite", "GoogleGenAI", "gemini-3.1-flash-lite"),
]

PROVIDER_LINE = re.compile(r"^(\s*)provider:\s*\S+\s*$", re.MULTILINE)
MODEL_LINE = re.compile(r"^(\s*)model:\s*\S+\s*$", re.MULTILINE)


def switch_model(original: str, provider: str, model: str) -> str:
    """Swap every provider/model line, leaving prompts and comments untouched."""
    text = PROVIDER_LINE.sub(rf"\g<1>provider: {provider}", original)
    return MODEL_LINE.sub(rf"\g<1>model: {model}", text)


def check_langsmith() -> bool:
    try:
        from dotenv import load_dotenv
        from langsmith import Client

        load_dotenv()
        Client().read_project(project_name=os.getenv("LANGSMITH_PROJECT", "default"))
        return True
    except Exception as exc:
        print(f"  LangSmith unreachable: {type(exc).__name__}")
        print(f"  {str(exc)[:100]}")
        return False


def run_eval(label: str) -> bool:
    env = {**os.environ, "LANGSMITH_RUN_LABEL": label}
    result = subprocess.run([sys.executable, "-m", "evals.run_eval"], env=env)
    return result.returncode == 0


def run_step(description: str, command: list[str]) -> bool:
    print(f"\n=== {description} ===")
    return subprocess.run(command).returncode == 0


def main(only: str | None, dry_run: bool, skip_trace_check: bool) -> None:
    if not AGENTS_PATH.exists():
        print(f"{AGENTS_PATH} not found. Run this from the project root.")
        return

    planned = [m for m in MODELS if only is None or m[0] == only]
    if not planned:
        names = ", ".join(label for label, _, _ in MODELS)
        print(f"No model matches '{only}'. Known models: {names}")
        return

    print("Planned runs (25 questions each):")
    for label, provider, model in planned:
        print(f"  {label:<20} provider={provider:<12} model={model}")

    print("\nChecking LangSmith...")
    traced = check_langsmith()
    if traced:
        print("  OK - traces will be recorded, so cost and latency will be captured.")
    elif not skip_trace_check and not dry_run:
        print(
            "\nStopping. Without tracing you would pay for every run and still get "
            "no cost data. Fix LANGSMITH_API_KEY in .env, or pass --skip-trace-check "
            "to run for accuracy only."
        )
        return

    if dry_run:
        print("\nDry run - nothing was executed.")
        return

    original = AGENTS_PATH.read_text(encoding="utf-8", newline="")
    completed: list[str] = []

    try:
        for label, provider, model in planned:
            print(f"\n=== {label} ({provider}/{model}) ===")
            AGENTS_PATH.write_text(
                switch_model(original, provider, model),
                encoding="utf-8",
                newline="",
            )
            if run_eval(label):
                completed.append(label)
            else:
                print(f"  {label} failed; carrying on with the rest.")
    finally:
        AGENTS_PATH.write_text(original, encoding="utf-8", newline="")
        print(f"\nRestored {AGENTS_PATH} to its original models.")

    if not completed:
        print("No run finished, so there is nothing to compare.")
        return

    print(f"\nFinished: {', '.join(completed)}")

    if traced:
        run_step(
            "Downloading traces", [sys.executable, "langsmith_report_download.py"]
        )

    run_step("Comparison", [sys.executable, "compare_models.py"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate each model in turn and compare accuracy against cost."
    )
    parser.add_argument("--only", help="Run a single model by label.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show the plan without spending money."
    )
    parser.add_argument(
        "--skip-trace-check",
        action="store_true",
        help="Run even if LangSmith is unreachable (accuracy only, no cost data).",
    )
    args = parser.parse_args()
    main(args.only, args.dry_run, args.skip_trace_check)
