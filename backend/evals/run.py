"""CLI: `uv run python -m evals.run {live,replay} [options]` from backend/.

live   Real Claude calls (needs ANTHROPIC_API_KEY). N trials per scenario,
       gated on pass rate. --record saves cassettes, the baseline and a
       dated results file for committing.
replay Recorded responses, no API key, no cost. One trial per scenario.

Exit status is 1 when the gate fails, so CI goes red.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from evals.report import BASELINE_PATH, baseline_from, load_baseline, to_markdown
from evals.scenarios import by_id
from evals.suite import TrialResult, run_live, run_replay
from fleetalert import config

RESULTS_DIR = Path(__file__).parent / "results"
MAX_TRIALS = 5  # cost guard: 6 scenarios x 5 trials is still ~$1.50


def _progress(scenario: object, n: int, result: TrialResult) -> None:
    sid = getattr(scenario, "scenario_id", "?")
    status = "pass" if result.passed else "FAIL"
    print(
        f"  {sid} #{n + 1}: {status} -> {' -> '.join(result.labels) or result.trial.error} "
        f"(${result.metric('estimated_cost_usd'):.4f}, {result.latency_ms / 1000:.1f} s)",
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run")
    parser.add_argument("tier", choices=["live", "replay"])
    parser.add_argument("--scenario", action="append", help="limit to these scenario ids (repeatable)")
    parser.add_argument("--model", default=None, help="live tier model (default: FLEETALERT_MODEL or claude-sonnet-5)")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--record", action="store_true", help="save cassettes, baseline and results")
    parser.add_argument("--summary", type=Path, help="append the markdown report here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--json", type=Path, help="write the full results JSON here")
    args = parser.parse_args(argv)

    # The loop logs every step as JSON; keep the eval output readable.
    logging.disable(logging.INFO)
    scenarios = by_id(args.scenario)

    if args.tier == "live":
        import anthropic

        if not 1 <= args.trials <= MAX_TRIALS:
            parser.error(f"--trials must be between 1 and {MAX_TRIALS}")
        model = args.model or config.anthropic_model()
        print(f"Live eval: {len(scenarios)} scenarios x {args.trials} trials on {model}", flush=True)
        suite, cassettes = run_live(
            scenarios,
            client=anthropic.Anthropic(max_retries=4),
            model=model,
            trials=args.trials,
            record=args.record,
            on_trial=_progress,
        )
    else:
        suite, cassettes = run_replay(scenarios), []

    report = to_markdown(suite, load_baseline())
    print(report)
    if args.summary:
        with args.summary.open("a") as fh:
            fh.write(report)
    results = suite.as_dict()
    if args.json:
        args.json.write_text(json.dumps(results, indent=2) + "\n")

    if args.record:
        for cassette in cassettes:
            print(f"recorded {cassette.save()}")
        if not suite.gate_failures():
            BASELINE_PATH.write_text(json.dumps(baseline_from(suite), indent=2) + "\n")
            print(f"updated {BASELINE_PATH}")
        RESULTS_DIR.mkdir(exist_ok=True)
        stamp = suite.started_at[:16].replace(":", "")  # e.g. 2026-09-30T1238
        dated = RESULTS_DIR / f"{stamp}-{suite.model}.json"
        dated.write_text(json.dumps(results, indent=2) + "\n")
        print(f"wrote {dated}")

    for failure in suite.gate_failures():
        print(f"::error::eval gate: {failure}")
    return 1 if suite.gate_failures() else 0


if __name__ == "__main__":
    sys.exit(main())
