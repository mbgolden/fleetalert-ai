"""Runs a scenario end to end: seed, investigate, (reject, re-investigate).

Each trial gets its own in-memory DynamoDB (moto) seeded exactly like the
live demo, and runs the production code path -- run_investigation and
reject_fix, the real Capabilities Engine and guardrails. Only the model
client varies: a real anthropic client (live tier), a replay of recorded
responses (replay tier), or a scripted fake (harness tests).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from moto import mock_aws

from evals.scenarios import ROUTED, Scenario
from fleetalert import autonomous, repositories
from fleetalert.agent.loop import reject_fix, run_investigation
from fleetalert.db import get_dynamodb_resource
from fleetalert.seed_data import reseed_demo_data
from fleetalert.tracing import Stopwatch

# Evals generate detector telemetry at a fixed moment, so every trial (and
# every recording's fingerprint) sees identical readings.
EVAL_DETECTOR_NOW = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)

# (round index) -> model client for that round.
ClientFactory = Callable[[int], Any]


@dataclass
class RoundRecord:
    outcome: dict[str, Any]
    spans: list[dict[str, Any]]

    @property
    def label(self) -> str:
        """The round's end state in the scenarios' vocabulary."""
        if self.outcome.get("outcome") == "awaiting_confirmation":
            return str(self.outcome.get("fix_id"))
        if self.outcome.get("outcome") == "routed_to_support":
            return ROUTED
        return str(self.outcome.get("outcome"))

    def spans_named(self, name: str) -> list[dict[str, Any]]:
        return [s for s in self.spans if s["name"] == name]

    @property
    def root(self) -> dict[str, Any] | None:
        return next((s for s in self.spans if s["kind"] == "investigation"), None)


@dataclass
class TrialRecord:
    scenario_id: str
    rounds: list[RoundRecord] = field(default_factory=list)
    error: str | None = None
    wall_ms: float = 0.0


@contextmanager
def isolated_demo_data() -> Iterator[None]:
    """A private, freshly seeded copy of the demo tables for one trial."""
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        os.environ.setdefault(var, "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    get_dynamodb_resource.cache_clear()
    with mock_aws():
        repositories.create_tables()
        reseed_demo_data()
        yield
    get_dynamodb_resource.cache_clear()


def run_trial(scenario: Scenario, client_for_round: ClientFactory, *, model: str) -> TrialRecord:
    trial = TrialRecord(scenario_id=scenario.scenario_id)
    watch = Stopwatch()
    with isolated_demo_data():
        try:
            if scenario.detector_profile:
                autonomous.run_detector(
                    lambda *_args: None, trigger="eval", profile=scenario.detector_profile, now=EVAL_DETECTOR_NOW
                )
            for index, expectation in enumerate(scenario.rounds):
                outcome = run_investigation(
                    scenario.alert_id, client_for_round(index), model=model, entry_point=scenario.entry_point
                )
                alert = repositories.get_alert(scenario.alert_id) or {}
                spans = repositories.get_trace(str(alert.get("current_trace_id")))
                trial.rounds.append(RoundRecord(outcome=outcome, spans=spans))
                if expectation.reject_with is None:
                    break
                if outcome.get("outcome") != "awaiting_confirmation":
                    break  # nothing to reject; the grader reports the missing round
                reject_fix(scenario.alert_id, reason=expectation.reject_with)
        except Exception as exc:  # noqa: BLE001 -- a crash is a graded failure, not a harness error
            trial.error = f"{type(exc).__name__}: {exc}"
    trial.wall_ms = watch.elapsed_ms()
    return trial
