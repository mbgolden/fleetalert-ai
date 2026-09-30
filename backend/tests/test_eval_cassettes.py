from __future__ import annotations

from pathlib import Path

from evals.cassettes import Cassette, RecordingClient, fingerprint
from evals.harness import run_trial
from evals.scenarios import by_id
from evals.suite import replay_scenario
from tests.fakes import FakeAnthropicClient, response, text_block, tool_use_block

MODEL = "claude-sonnet-5"


def _record(scenario_id: str, tmp_path: Path) -> Cassette:
    scenario = by_id([scenario_id])[0]
    fake = FakeAnthropicClient(
        [
            response(text_block("Checking telemetry."), tool_use_block("get_telemetry_snapshot", {"window_minutes": 60}, "t1")),
            response(tool_use_block("search_knowledge_base", {"symptom_description": "temperature drift"}, "t2")),
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "send_diagnostic_reset", "description": "Matches KB-003.", "confidence": 0.8},
                    "t3",
                )
            ),
        ]
    )
    recorder = RecordingClient(fake)
    run_trial(scenario, lambda _: recorder, model=MODEL)
    cassette = Cassette(scenario_id, MODEL, "2026-09-29T00:00:00+00:00", [recorder.recorded])
    cassette.save(tmp_path)
    loaded = Cassette.load(scenario_id, tmp_path)
    assert loaded is not None
    return loaded


def test_recorded_trajectory_replays_identically(tmp_path: Path) -> None:
    cassette = _record("cabin-drift", tmp_path)

    assert len(cassette.rounds[0].responses) == 3
    assert cassette.rounds[0].responses[0]["content"][0] == {"type": "text", "text": "Checking telemetry."}

    result = replay_scenario(by_id(["cabin-drift"])[0], cassette)
    assert result.passed
    assert not result.stale
    assert result.labels == ["send_diagnostic_reset"]


def test_prompt_or_tool_change_marks_the_cassette_stale(tmp_path: Path) -> None:
    cassette = _record("cabin-drift", tmp_path)
    cassette.rounds[0].fingerprint = "recorded-under-an-older-prompt"

    assert replay_scenario(by_id(["cabin-drift"])[0], cassette).stale


def test_a_code_path_that_needs_more_model_calls_fails_replay(tmp_path: Path) -> None:
    cassette = _record("cabin-drift", tmp_path)
    cassette.rounds[0].responses = cassette.rounds[0].responses[:2]

    result = replay_scenario(by_id(["cabin-drift"])[0], cassette)
    assert not result.passed
    assert "ReplayExhausted" in (result.trial.error or "")


def test_fingerprint_covers_prompt_tools_and_opening_message() -> None:
    base = {"model": MODEL, "system": "s", "tools": [{"name": "a"}], "messages": [{"role": "user", "content": "go"}]}
    assert fingerprint(base) == fingerprint({**base, "messages": [*base["messages"], {"role": "assistant"}]})
    assert fingerprint(base) != fingerprint({**base, "system": "s2"})
    assert fingerprint(base) != fingerprint({**base, "tools": [{"name": "b"}]})
    assert fingerprint(base) != fingerprint({**base, "messages": [{"role": "user", "content": "other"}]})
