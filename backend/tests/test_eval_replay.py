"""Replay tier: every recorded real-model trajectory must still pass.

Free and deterministic, so it runs on every PR. A failure here means a code
change broke a trajectory the real model produced. A stale cassette (the
prompt or tools changed since recording) is skipped: re-record it with the
live tier (`Evals (live)` workflow, record = true).
"""

from __future__ import annotations

import pytest

from evals.cassettes import Cassette
from evals.scenarios import SCENARIOS, Scenario
from evals.suite import replay_scenario


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.scenario_id)
def test_recorded_trajectory_still_passes(scenario: Scenario) -> None:
    cassette = Cassette.load(scenario.scenario_id)
    if cassette is None:
        pytest.skip("no cassette recorded yet")

    result = replay_scenario(scenario, cassette)

    if result.stale:
        pytest.skip("stale cassette: prompt or tools changed since recording; re-record with the live tier")
    failing = [f"{g.name}: {g.detail}" for g in result.grades if g.gating and not g.passed]
    assert result.passed, f"{scenario.scenario_id} regressed: {failing} (error: {result.trial.error})"
