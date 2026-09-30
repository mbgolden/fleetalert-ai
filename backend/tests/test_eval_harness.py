"""The eval harness grading scripted trajectories: an eval that can't tell a
bad investigation from a good one is worse than none, so each gating check
is shown failing on a trajectory built to trip it."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from evals.graders import grade_trial, trial_passed
from evals.harness import run_trial
from evals.report import to_markdown
from evals.scenarios import ROUTED, by_id
from evals.suite import ScenarioResult, SuiteResult, TrialResult
from tests.fakes import FakeAnthropicClient, response, tool_use_block

MODEL = "claude-sonnet-5"


def _investigation(
    fix_id: str,
    description: str = "Matches KB evidence.",
    *,
    confidence: float = 0.8,
    telemetry: bool = True,
) -> FakeAnthropicClient:
    steps: list[SimpleNamespace] = []
    if telemetry:
        steps.append(response(tool_use_block("get_telemetry_snapshot", {"window_minutes": 60}, "t1")))
    steps.append(response(tool_use_block("search_knowledge_base", {"symptom_description": "symptom"}, "t2")))
    steps.append(
        response(
            tool_use_block(
                "propose_fix",
                {"fix_id": fix_id, "description": description, "confidence": confidence},
                "t3",
            )
        )
    )
    return FakeAnthropicClient(steps)


def _grade(scenario_id: str, *clients: FakeAnthropicClient) -> tuple[bool, dict[str, Any]]:
    scenario = by_id([scenario_id])[0]
    trial = run_trial(scenario, lambda i: clients[i], model=MODEL)
    grades = grade_trial(scenario, trial)
    return trial_passed(grades), {g.name: g for g in grades}


def test_correct_investigation_passes() -> None:
    passed, grades = _grade("cabin-drift", _investigation("send_diagnostic_reset"))
    assert passed
    assert grades["round 1: outcome"].detail.startswith("got send_diagnostic_reset")


def test_wrong_fix_fails_outcome() -> None:
    passed, grades = _grade(
        "sensor-glitch", _investigation("schedule_service_visit", "KB-001 and KB-002 conflict.")
    )
    assert not passed
    assert not grades["round 1: outcome"].passed


def test_proposing_without_reading_telemetry_fails_evidence() -> None:
    passed, grades = _grade("cabin-drift", _investigation("send_diagnostic_reset", telemetry=False))
    assert not passed
    assert "get_telemetry_snapshot" in grades["round 1: gathered evidence first"].detail


def test_ignoring_the_kb_conflict_fails() -> None:
    passed, grades = _grade("sensor-glitch", _investigation("restart_sensor", "Sensor glitch."))
    assert not passed
    assert not grades["acknowledged the KB conflict"].passed


def test_noting_the_kb_conflict_passes() -> None:
    passed, _ = _grade(
        "sensor-glitch",
        _investigation("restart_sensor", "KB-001 and KB-002 disagree; the telemetry shows one spike."),
    )
    assert passed


def test_rejection_round_that_routes_to_support_passes() -> None:
    passed, grades = _grade(
        "oil-pressure-rejected",
        _investigation("schedule_service_visit"),
        _investigation("escalate_to_technician", "Nothing remote fits KB-004.", confidence=0.4),
    )
    assert passed
    assert grades["round 2: outcome"].detail.startswith(f"got {ROUTED}")


def test_reproposing_a_rejected_fix_fails_even_though_the_guardrail_catches_it() -> None:
    passed, grades = _grade(
        "oil-pressure-rejected",
        _investigation("schedule_service_visit"),
        _investigation("schedule_service_visit"),
    )
    assert not passed
    assert not grades["round 2: respected rejection"].passed


def test_rejection_scenario_whose_first_round_routes_reports_the_missing_round() -> None:
    passed, grades = _grade("oil-pressure-rejected", _investigation("escalate_to_technician"))
    assert not passed
    assert grades["round 2: outcome"].detail == "round never ran"


def test_overconfidence_without_kb_support_warns_but_does_not_gate() -> None:
    passed, grades = _grade("compressor-no-kb", _investigation("schedule_service_visit", confidence=0.95))
    assert passed
    confidence = grades["confidence <= 0.7"]
    assert not confidence.passed and not confidence.gating


def test_a_crash_is_a_failed_trial_not_a_harness_error() -> None:
    passed, grades = _grade("cabin-drift", FakeAnthropicClient([]))
    assert not passed
    assert "AssertionError" in grades["ran without crashing"].detail


def test_report_and_gate() -> None:
    scenario = by_id(["cabin-drift"])[0]
    good = run_trial(scenario, lambda _: _investigation("send_diagnostic_reset"), model=MODEL)
    bad = run_trial(scenario, lambda _: _investigation("restart_sensor"), model=MODEL)
    trials = [TrialResult(t, g := grade_trial(scenario, t), trial_passed(g)) for t in (good, good, bad)]
    suite = SuiteResult("live", MODEL, "2026-09-29T00:00:00+00:00", [ScenarioResult(scenario, trials)])

    assert suite.gate_failures() == ["overall pass rate 67% < 80%"]
    report = to_markdown(suite, {"model": MODEL, "overall_pass_rate": 1.0, "scenarios": {"cabin-drift": {"pass_rate": 1.0}}})
    assert "FAIL" in report
    assert "| `cabin-drift` | 2/3 (-33%)" in report
    assert "restart_sensor ×1" in report
