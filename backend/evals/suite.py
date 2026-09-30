"""Runs scenarios for N trials and aggregates pass rates, cost and latency."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from evals.cassettes import Cassette, RecordedRound, RecordingClient, ReplayClient
from evals.graders import Grade, grade_trial, num, trial_passed
from evals.harness import TrialRecord, run_trial
from evals.scenarios import Scenario

# Gate for the live tier. With 3 trials, 2/3 per scenario tolerates one
# unlucky sample; the overall bar keeps several 2/3s from adding up to a pass.
MIN_SCENARIO_PASS_RATE = 2 / 3
MIN_OVERALL_PASS_RATE = 0.8


@dataclass
class TrialResult:
    trial: TrialRecord
    grades: list[Grade]
    passed: bool
    stale: bool = False

    @property
    def labels(self) -> list[str]:
        return [r.label for r in self.trial.rounds]

    def metric(self, attribute: str) -> float:
        total = 0.0
        for rnd in self.trial.rounds:
            value = num((rnd.root or {}).get("attributes", {}).get(attribute))
            total += value or 0.0
        return total

    @property
    def latency_ms(self) -> float:
        return sum(num((rnd.root or {}).get("latency_ms")) or 0.0 for rnd in self.trial.rounds)

    def as_dict(self) -> dict[str, Any]:
        proposals = [
            {
                "round": i + 1,
                "fix_id": (s.get("input") or {}).get("fix_id"),
                "confidence": num((s.get("input") or {}).get("confidence")),
                "description": (s.get("input") or {}).get("description"),
            }
            for i, rnd in enumerate(self.trial.rounds)
            for s in rnd.spans_named("propose_fix")
            if s["status"] == "success"
        ]
        return {
            "passed": self.passed,
            "stale": self.stale,
            "outcomes": self.labels,
            "error": self.trial.error,
            "cost_usd": round(self.metric("estimated_cost_usd"), 6),
            "model_calls": int(self.metric("model_calls")),
            "input_tokens": int(self.metric("input_tokens")),
            "output_tokens": int(self.metric("output_tokens")),
            "latency_ms": round(self.latency_ms, 1),
            "grades": [
                {"name": g.name, "passed": g.passed, "gating": g.gating, "detail": g.detail}
                for g in self.grades
            ],
            "proposals": proposals,
        }


@dataclass
class ScenarioResult:
    scenario: Scenario
    trials: list[TrialResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return sum(t.passed for t in self.trials) / len(self.trials) if self.trials else 0.0

    @property
    def outcome_counts(self) -> Counter[str]:
        return Counter(" -> ".join(t.labels) or "none" for t in self.trials)

    def mean(self, value: Callable[[TrialResult], float]) -> float:
        return sum(value(t) for t in self.trials) / len(self.trials) if self.trials else 0.0

    def failing_grades(self) -> Counter[str]:
        return Counter(g.name for t in self.trials for g in t.grades if g.gating and not g.passed)

    def warnings(self) -> Counter[str]:
        return Counter(g.name for t in self.trials for g in t.grades if not g.gating and not g.passed)


@dataclass
class SuiteResult:
    tier: str
    model: str
    started_at: str
    scenarios: list[ScenarioResult]

    @property
    def overall_pass_rate(self) -> float:
        trials = [t for s in self.scenarios for t in s.trials]
        return sum(t.passed for t in trials) / len(trials) if trials else 0.0

    @property
    def total_cost_usd(self) -> float:
        return sum(t.metric("estimated_cost_usd") for s in self.scenarios for t in s.trials)

    def gate_failures(self) -> list[str]:
        # Scenarios with no trials (replay without a cassette) aren't graded.
        problems = [
            f"{s.scenario.scenario_id}: pass rate {s.pass_rate:.0%} < {MIN_SCENARIO_PASS_RATE:.0%}"
            for s in self.scenarios
            if s.trials and s.pass_rate < MIN_SCENARIO_PASS_RATE
        ]
        if any(s.trials for s in self.scenarios) and self.overall_pass_rate < MIN_OVERALL_PASS_RATE:
            problems.append(f"overall pass rate {self.overall_pass_rate:.0%} < {MIN_OVERALL_PASS_RATE:.0%}")
        return problems

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "model": self.model,
            "started_at": self.started_at,
            "overall_pass_rate": round(self.overall_pass_rate, 4),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "gate": {
                "min_scenario_pass_rate": round(MIN_SCENARIO_PASS_RATE, 4),
                "min_overall_pass_rate": MIN_OVERALL_PASS_RATE,
                "failures": self.gate_failures(),
            },
            "scenarios": {
                s.scenario.scenario_id: {
                    "alert_id": s.scenario.alert_id,
                    "pass_rate": round(s.pass_rate, 4),
                    "trials": [t.as_dict() for t in s.trials],
                }
                for s in self.scenarios
            },
        }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_live(
    scenarios: list[Scenario],
    *,
    client: Any,
    model: str,
    trials: int,
    record: bool = False,
    on_trial: Callable[[Scenario, int, TrialResult], None] | None = None,
) -> tuple[SuiteResult, list[Cassette]]:
    """Real model calls. Optionally keeps the first passing trial of each
    scenario as a cassette for the replay tier."""
    suite = SuiteResult(tier="live", model=model, started_at=_now(), scenarios=[])
    cassettes: list[Cassette] = []
    for scenario in scenarios:
        result = ScenarioResult(scenario)
        for n in range(trials):
            recorders: list[RecordingClient] = []

            def client_for_round(_index: int, recorders: list[RecordingClient] = recorders) -> RecordingClient:
                recorder = RecordingClient(client)
                recorders.append(recorder)
                return recorder

            trial = run_trial(scenario, client_for_round, model=model)
            grades = grade_trial(scenario, trial)
            trial_result = TrialResult(trial, grades, trial_passed(grades))
            result.trials.append(trial_result)
            if on_trial:
                on_trial(scenario, n, trial_result)
            if record and trial_result.passed and not any(c.scenario_id == scenario.scenario_id for c in cassettes):
                cassettes.append(
                    Cassette(scenario.scenario_id, model, _now(), [r.recorded for r in recorders])
                )
        suite.scenarios.append(result)
    return suite, cassettes


def replay_scenario(scenario: Scenario, cassette: Cassette) -> TrialResult:
    replayers: list[ReplayClient] = []

    def client_for_round(index: int) -> ReplayClient:
        # A round the recording doesn't have replays nothing, so the loop
        # fails with ReplayExhausted and the trial is graded as diverged.
        recorded = cassette.rounds[index] if index < len(cassette.rounds) else RecordedRound()
        replayer = ReplayClient(recorded)
        replayers.append(replayer)
        return replayer

    trial = run_trial(scenario, client_for_round, model=cassette.model)
    grades = grade_trial(scenario, trial)
    return TrialResult(trial, grades, trial_passed(grades), stale=any(r.stale for r in replayers))


def run_replay(scenarios: list[Scenario]) -> SuiteResult:
    suite = SuiteResult(tier="replay", model="(recorded)", started_at=_now(), scenarios=[])
    for scenario in scenarios:
        cassette = Cassette.load(scenario.scenario_id)
        result = ScenarioResult(scenario)
        if cassette is not None:
            suite.model = cassette.model
            result.trials.append(replay_scenario(scenario, cassette))
        suite.scenarios.append(result)
    return suite
