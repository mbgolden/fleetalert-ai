"""Markdown summary (for the GitHub job summary) and baseline comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.suite import SuiteResult

BASELINE_PATH = Path(__file__).parent / "baseline.json"


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.is_file() else None


def baseline_from(suite: SuiteResult) -> dict[str, Any]:
    """The slice of a live run worth versioning: rates and costs, no transcripts."""
    return {
        "model": suite.model,
        "recorded_at": suite.started_at,
        "overall_pass_rate": round(suite.overall_pass_rate, 4),
        "scenarios": {
            s.scenario.scenario_id: {
                "pass_rate": round(s.pass_rate, 4),
                "trials": len(s.trials),
                "mean_cost_usd": round(s.mean(lambda t: t.metric("estimated_cost_usd")), 6),
                "mean_latency_ms": round(s.mean(lambda t: t.latency_ms), 1),
            }
            for s in suite.scenarios
        },
    }


def _delta(now: float, before: float | None) -> str:
    if before is None:
        return ""
    diff = now - before
    if abs(diff) < 0.005:
        return " (=)"
    return f" ({'+' if diff > 0 else ''}{diff:.0%})"


def to_markdown(suite: SuiteResult, baseline: dict[str, Any] | None = None) -> str:
    base_scenarios = (baseline or {}).get("scenarios", {})
    failures = suite.gate_failures()
    verdict = "PASS" if not failures else "FAIL"
    lines = [
        f"## FleetAlert agent evals: {verdict}",
        "",
        (
            f"Tier **{suite.tier}** · model `{suite.model}` · "
            f"overall pass rate **{suite.overall_pass_rate:.0%}**"
            f"{_delta(suite.overall_pass_rate, (baseline or {}).get('overall_pass_rate'))} · "
            f"total cost ${suite.total_cost_usd:.3f}"
        ),
        "",
    ]
    if baseline:
        lines += [f"Compared with baseline `{baseline.get('model')}` from {baseline.get('recorded_at')}.", ""]
    lines += [
        "| Scenario | Pass rate | Outcomes | Mean cost | Mean latency | Failing checks | Warnings |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in suite.scenarios:
        sid = s.scenario.scenario_id
        if not s.trials:
            lines.append(f"| `{sid}` | skipped (no cassette) | | | | | |")
            continue
        before = base_scenarios.get(sid, {}).get("pass_rate")
        stale = any(t.stale for t in s.trials)
        outcomes = ", ".join(f"{label} ×{n}" for label, n in s.outcome_counts.most_common())
        failing = ", ".join(f"{name} ×{n}" for name, n in s.failing_grades().most_common())
        warnings = ", ".join(f"{name} ×{n}" for name, n in s.warnings().most_common())
        lines.append(
            f"| `{sid}`{' (stale)' if stale else ''} "
            f"| {sum(t.passed for t in s.trials)}/{len(s.trials)}{_delta(s.pass_rate, before)} "
            f"| {outcomes} "
            f"| ${s.mean(lambda t: t.metric('estimated_cost_usd')):.4f} "
            f"| {s.mean(lambda t: t.latency_ms) / 1000:.1f} s "
            f"| {failing or '—'} | {warnings or '—'} |"
        )
    if failures:
        lines += ["", "**Gate failures**", *[f"- {f}" for f in failures]]
    if any(t.stale for s in suite.scenarios for t in s.trials):
        lines += [
            "",
            (
                "_Stale: the prompt or tool definitions changed since the recording, so replay "
                "only proves the code path still works. The live tier is the real signal._"
            ),
        ]
    failed = [(s, n, t) for s in suite.scenarios for n, t in enumerate(s.trials, 1) if not t.passed]
    if failed:
        lines += ["", "<details><summary>Failed trial details</summary>", ""]
        for s, n, t in failed:
            lines.append(f"**{s.scenario.scenario_id} #{n}** → {' -> '.join(t.labels) or 'no rounds'}")
            lines += [f"- {g.name}: {g.detail}" for g in t.grades if g.gating and not g.passed]
            lines.append("")
        lines.append("</details>")
    return "\n".join(lines) + "\n"
