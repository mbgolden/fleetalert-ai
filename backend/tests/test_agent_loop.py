import pytest

from fleetalert.agent.guardrails import GuardrailViolation
from fleetalert.agent.loop import confirm_fix, execute_fix, reject_fix, run_investigation
from fleetalert.repositories import (
    create_alert,
    get_alert,
    put_knowledge_base_entry,
    put_machine,
    update_alert,
    update_alert_if_current,
)
from fleetalert.seed_data import SEED_KNOWLEDGE_BASE, SEED_MACHINES
from tests.fakes import FakeAnthropicClient, response, text_block, tool_use_block
from tests.trace_helpers import event_names, last_event, round_spans
from tests.trace_helpers import events as events_for


def _seed(*, alert_id: str, machine_id: str, alert_type: str, severity: str = "medium") -> None:
    for machine in SEED_MACHINES:
        put_machine(machine)
    for entry in SEED_KNOWLEDGE_BASE:
        put_knowledge_base_entry(entry)
    create_alert(
        {
            "alert_id": alert_id,
            "machine_id": machine_id,
            "org_id": "org-demo",
            "alert_type": alert_type,
            "severity": severity,
            "status": "open",
            "created_at": "2026-09-17T10:00:00+00:00",
        }
    )


def test_run_investigation_whitelisted_fix_awaits_confirmation(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-1", machine_id="M-1002", alert_type="temperature_drift")

    client = FakeAnthropicClient(
        [
            response(tool_use_block("get_telemetry_snapshot", {"window_minutes": 30}, "t1")),
            response(tool_use_block("search_knowledge_base", {"symptom_description": "temperature drift"}, "t2")),
            response(
                tool_use_block(
                    "propose_fix",
                    {
                        "fix_id": "send_diagnostic_reset",
                        "description": "Cabin temp drifting, matches KB-003.",
                        "confidence": 0.85,
                    },
                    "t3",
                )
            ),
        ]
    )

    result = run_investigation("ALERT-1", client)

    assert result["outcome"] == "awaiting_confirmation"
    assert result["fix_id"] == "send_diagnostic_reset"
    assert "confirmation_token" in result

    alert = get_alert("ALERT-1")
    assert alert is not None
    assert alert["status"] == "awaiting_confirmation"
    assert alert["confirmation_token"] == result["confirmation_token"]

    assert event_names("ALERT-1") == [
        "investigation_started",
        "get_telemetry_snapshot",
        "search_knowledge_base",
        "propose_fix",
        "guardrail.whitelist",
        "request_confirmation",
    ]


def test_run_investigation_non_whitelisted_fix_routes_to_support(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-2", machine_id="M-1001", alert_type="coolant_temp_spike")

    client = FakeAnthropicClient(
        [
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "replace_engine", "description": "...", "confidence": 0.9},
                )
            )
        ]
    )

    result = run_investigation("ALERT-2", client)

    assert result == {
        "outcome": "routed_to_support",
        "alert_id": "ALERT-2",
        "reason": "fix_not_whitelisted",
    }
    alert = get_alert("ALERT-2")
    assert alert is not None
    assert alert["status"] == "routed_to_support"

    last_action = last_event("ALERT-2")
    assert last_action["action"] == "route_to_support"
    assert last_action["details"]["fix_id"] == "replace_engine"


def test_run_investigation_max_iterations_forces_route_to_support(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-3", machine_id="M-1003", alert_type="oil_pressure_warning")

    client = FakeAnthropicClient([response(text_block()), response(text_block())])

    result = run_investigation("ALERT-3", client, max_iterations=2)

    assert result == {
        "outcome": "routed_to_support",
        "alert_id": "ALERT-3",
        "reason": "max_iterations_exceeded",
    }
    assert get_alert("ALERT-3")["status"] == "routed_to_support"  # type: ignore[index]


def test_run_investigation_is_a_no_op_for_a_duplicate_trigger(dynamodb_tables: None) -> None:
    """A duplicate /investigate trigger (or a retried Step Functions
    execution) landing after an earlier attempt already won should report
    that attempt's outcome, not start a second investigation from scratch.
    """
    _seed(alert_id="ALERT-8", machine_id="M-1002", alert_type="temperature_drift")
    update_alert(
        "ALERT-8",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confidence=0.9,
        confirmation_token="already-won-token",
    )

    client = FakeAnthropicClient([])  # would raise if the loop tried to call Claude

    result = run_investigation("ALERT-8", client)

    assert result == {
        "outcome": "awaiting_confirmation",
        "alert_id": "ALERT-8",
        "fix_id": "send_diagnostic_reset",
        "confirmation_token": "already-won-token",
    }
    # unchanged -- the duplicate trigger never touched it
    assert get_alert("ALERT-8")["confirmation_token"] == "already-won-token"  # type: ignore[index]


def test_execute_fix_requires_matching_confirmation_token(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-4", machine_id="M-1002", alert_type="temperature_drift")
    update_alert(
        "ALERT-4",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confirmation_token="correct-token",
    )

    with pytest.raises(GuardrailViolation, match="Invalid confirmation token"):
        execute_fix("ALERT-4", "send_diagnostic_reset", "wrong-token")

    result = execute_fix("ALERT-4", "send_diagnostic_reset", "correct-token")
    assert result["outcome"] == "resolved"
    assert get_alert("ALERT-4")["status"] == "resolved"  # type: ignore[index]

    assert event_names("ALERT-4")[-1] == "execute_fix"


def test_execute_fix_rejects_when_a_concurrent_request_already_resolved_it(
    dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """execute_fix's own status/token checks read the alert first, same as
    always -- this exercises what happens when reality changes between
    that read and execute_fix's own conditional write, i.e. the actual
    race the ConditionExpression guards against, not just the ordinary
    "wrong status to begin with" case already covered elsewhere.
    """
    _seed(alert_id="ALERT-9", machine_id="M-1002", alert_type="temperature_drift")
    update_alert(
        "ALERT-9",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confirmation_token="tok",
    )
    stale_alert = get_alert("ALERT-9")

    # A concurrent request wins the race between execute_fix's read and its
    # own write.
    update_alert_if_current("ALERT-9", expected_status="awaiting_confirmation", status="resolved")
    monkeypatch.setattr("fleetalert.agent.loop.repositories.get_alert", lambda alert_id: stale_alert)

    with pytest.raises(GuardrailViolation, match="already resolved or moved on"):
        execute_fix("ALERT-9", "send_diagnostic_reset", "tok")


def test_confirm_fix_logs_human_action_without_executing(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-4B", machine_id="M-1002", alert_type="temperature_drift")
    update_alert(
        "ALERT-4B",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confirmation_token="correct-token",
        step_functions_task_token="sfn-task-token",
    )

    with pytest.raises(GuardrailViolation, match="Invalid confirmation token"):
        confirm_fix("ALERT-4B", "wrong-token")

    result = confirm_fix("ALERT-4B", "correct-token")

    assert result == {
        "alert_id": "ALERT-4B",
        "fix_id": "send_diagnostic_reset",
        "confirmation_token": "correct-token",
        "step_functions_task_token": "sfn-task-token",
    }
    # confirming does not execute anything -- status is unchanged
    assert get_alert("ALERT-4B")["status"] == "awaiting_confirmation"  # type: ignore[index]

    last_action = last_event("ALERT-4B")
    assert last_action["actor"] == "human"
    assert last_action["action"] == "confirm"


def test_execute_fix_rejects_non_whitelisted_fix_as_defense_in_depth(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-5", machine_id="M-1002", alert_type="temperature_drift")
    update_alert(
        "ALERT-5",
        status="awaiting_confirmation",
        proposed_fix="replace_engine",
        confirmation_token="tok",
    )

    with pytest.raises(GuardrailViolation, match="not whitelisted"):
        execute_fix("ALERT-5", "replace_engine", "tok")


def test_execute_fix_requires_awaiting_confirmation_status(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-6", machine_id="M-1002", alert_type="temperature_drift")

    with pytest.raises(GuardrailViolation, match="not awaiting confirmation"):
        execute_fix("ALERT-6", "send_diagnostic_reset", "any-token")


def test_reject_fix_reinvestigates_instead_of_ending_the_flow(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-7", machine_id="M-1002", alert_type="temperature_drift")
    update_alert(
        "ALERT-7",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confirmation_token="tok",
    )

    result = reject_fix("ALERT-7", reason="visitor rejected")

    assert result["outcome"] == "investigating"
    assert result["alert_id"] == "ALERT-7"
    assert [r["fix_id"] for r in result["rejected_fixes"]] == ["send_diagnostic_reset"]

    alert = get_alert("ALERT-7")
    assert alert is not None
    assert alert["status"] == "investigating"
    assert alert["proposed_fix"] is None
    assert alert["confirmation_token"] is None
    assert [r["fix_id"] for r in alert["rejected_fixes"]] == ["send_diagnostic_reset"]
    assert alert["rejected_fixes"][0]["reason"] == "visitor rejected"

    last_action = last_event("ALERT-7")
    assert last_action["actor"] == "human"
    assert last_action["action"] == "reject"

    # The old proposal's token is dead -- execute_fix can't be replayed against it.
    with pytest.raises(GuardrailViolation):
        execute_fix("ALERT-7", "send_diagnostic_reset", "tok")

    # A follow-up investigation (as Step Functions' RunInvestigation loop-back
    # would trigger) sees the rejection history and proposes something else.
    client = FakeAnthropicClient(
        [
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "restart_sensor", "description": "Different root cause.", "confidence": 0.7},
                )
            )
        ]
    )
    result = run_investigation("ALERT-7", client)
    assert result["outcome"] == "awaiting_confirmation"
    assert result["fix_id"] == "restart_sensor"


def test_reject_fix_exhausts_budget_and_routes_to_support(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-7B", machine_id="M-1002", alert_type="temperature_drift")
    update_alert("ALERT-7B", status="awaiting_confirmation", proposed_fix="send_diagnostic_reset")

    # MAX_REJECTION_ROUNDS=1 -- the 1st reject loops back, the 2nd exhausts the budget.
    result = reject_fix("ALERT-7B", reason="still wrong")
    assert result["outcome"] == "investigating"

    update_alert("ALERT-7B", status="awaiting_confirmation", proposed_fix="restart_sensor")
    result = reject_fix("ALERT-7B", reason="still wrong")

    assert result == {
        "outcome": "routed_to_support",
        "alert_id": "ALERT-7B",
        "reason": "rejection_budget_exhausted",
    }
    alert = get_alert("ALERT-7B")
    assert alert is not None
    assert alert["status"] == "routed_to_support"
    assert len(alert["rejected_fixes"]) == 2

    last_action = last_event("ALERT-7B")
    assert last_action["action"] == "route_to_support"
    assert last_action["details"]["reason"] == "rejection_budget_exhausted"


def test_run_investigation_refuses_to_repropose_an_already_rejected_fix(dynamodb_tables: None) -> None:
    """Defense in depth: even if the model ignores the prompt's instruction
    not to repeat a rejected fix_id, the code enforces it independently.
    """
    _seed(alert_id="ALERT-7C", machine_id="M-1002", alert_type="temperature_drift")
    update_alert(
        "ALERT-7C",
        status="investigating",
        rejected_fixes=[{"fix_id": "send_diagnostic_reset", "reason": "nope", "rejected_at": "2026-01-01T00:00:00+00:00"}],
    )

    client = FakeAnthropicClient(
        [
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "send_diagnostic_reset", "description": "...", "confidence": 0.5},
                )
            )
        ]
    )
    result = run_investigation("ALERT-7C", client)

    assert result == {
        "outcome": "routed_to_support",
        "alert_id": "ALERT-7C",
        "reason": "fix_already_rejected",
    }
    assert get_alert("ALERT-7C")["status"] == "routed_to_support"  # type: ignore[index]


def test_propose_fix_without_fix_id_is_reported_to_the_model_not_raised(dynamodb_tables: None) -> None:
    """The model can omit a schema-required field; that must come back as a
    tool error it can correct, not crash the run (seen live on ALERT-1003).
    """
    _seed(alert_id="ALERT-10", machine_id="M-1002", alert_type="temperature_drift")

    client = FakeAnthropicClient(
        [
            response(tool_use_block("propose_fix", {"description": "oops", "confidence": 0.5}, "t1")),
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "restart_sensor", "description": "second try", "confidence": 0.6},
                    "t2",
                )
            ),
        ]
    )

    result = run_investigation("ALERT-10", client)

    assert result["outcome"] == "awaiting_confirmation"
    assert result["fix_id"] == "restart_sensor"


def test_malformed_tool_call_does_not_crash_the_loop(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-11", machine_id="M-1002", alert_type="temperature_drift")

    client = FakeAnthropicClient(
        [
            response(tool_use_block("get_telemetry_snapshot", {}, "t1")),  # missing window_minutes
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "restart_sensor", "description": "ok", "confidence": 0.7},
                    "t2",
                )
            ),
        ]
    )

    result = run_investigation("ALERT-11", client)

    assert result["outcome"] == "awaiting_confirmation"


def test_propose_fix_missing_description_or_confidence_is_retried(dynamodb_tables: None) -> None:
    """A proposal with only fix_id (seen live) must not reach the UI half-empty."""
    _seed(alert_id="ALERT-12", machine_id="M-1002", alert_type="temperature_drift")

    client = FakeAnthropicClient(
        [
            response(tool_use_block("propose_fix", {"fix_id": "restart_sensor"}, "t1")),
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "restart_sensor", "description": "full", "confidence": 0.8},
                    "t2",
                )
            ),
        ]
    )

    result = run_investigation("ALERT-12", client)

    assert result["outcome"] == "awaiting_confirmation"
    alert = get_alert("ALERT-12")
    assert alert is not None
    assert alert["root_cause_summary"] == "full"
    assert float(alert["confidence"]) == 0.8


def test_investigation_usage_is_recorded_with_an_estimated_cost(dynamodb_tables: None) -> None:
    from types import SimpleNamespace

    _seed(alert_id="ALERT-13", machine_id="M-1002", alert_type="temperature_drift")
    usage = SimpleNamespace(input_tokens=5_000, output_tokens=500)

    def with_usage(block: SimpleNamespace) -> SimpleNamespace:
        return SimpleNamespace(content=[block], usage=usage)

    client = FakeAnthropicClient(
        [
            with_usage(tool_use_block("search_knowledge_base", {"symptom_description": "temperature drift"}, "t1")),
            with_usage(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "send_diagnostic_reset", "description": "drift", "confidence": 0.8},
                    "t2",
                )
            ),
        ]
    )

    run_investigation("ALERT-13", client, model="claude-sonnet-5")

    (round_span,) = round_spans("ALERT-13")
    attrs = round_span["attributes"]
    assert attrs["model_calls"] == 2
    assert attrs["input_tokens"] == 10_000
    # 10K input at $2/M + 1K output at $10/M
    assert float(attrs["estimated_cost_usd"]) == 0.03


def test_tool_results_with_dynamodb_decimals_reach_the_model(dynamodb_tables: None) -> None:
    """Seeded telemetry comes back from DynamoDB as Decimal; json.dumps
    used to raise TypeError on it outside the tool-error handling, crashing
    every investigation that read telemetry.
    """
    import json

    from fleetalert.seed_data import reseed_demo_data

    reseed_demo_data()
    client = FakeAnthropicClient(
        [
            response(tool_use_block("get_telemetry_snapshot", {"window_minutes": 60}, "t1")),
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "restart_sensor", "description": "lone spike", "confidence": 0.8},
                    "t2",
                )
            ),
        ]
    )

    result = run_investigation("ALERT-1004", client)

    assert result["outcome"] == "awaiting_confirmation"
    sent = client.messages.calls[1]["messages"][2]["content"][0]["content"]
    readings = json.loads(sent)["readings"]
    assert any(r["signal_readings"]["coolant_temp_c"] == 121 for r in readings)


def _whitelisted_run(alert_id: str) -> FakeAnthropicClient:
    return FakeAnthropicClient(
        [
            response(
                text_block("Checking telemetry first."),
                tool_use_block("get_telemetry_snapshot", {"window_minutes": 30}, "t1"),
            ),
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "send_diagnostic_reset", "description": "drift", "confidence": 0.8},
                    "t2",
                )
            ),
        ]
    )


def test_a_round_is_one_trace_with_a_proper_span_tree(dynamodb_tables: None) -> None:
    from fleetalert.repositories import get_spans_for_alert

    _seed(alert_id="ALERT-20", machine_id="M-1002", alert_type="temperature_drift")

    run_investigation("ALERT-20", _whitelisted_run("ALERT-20"), entry_point="email")

    spans = get_spans_for_alert("ALERT-20")
    assert len({s["trace_id"] for s in spans}) == 1
    assert {s["entry_point"] for s in spans} == {"email"}

    (root,) = [s for s in spans if s["kind"] == "investigation"]
    assert root["parent_span_id"] is None
    assert root["output"]["outcome"] == "awaiting_confirmation"
    assert root["output"]["confirmation_token"] == "[redacted]"
    assert root["attributes"]["model_calls"] == 2

    model_calls = [s for s in spans if s["kind"] == "model_call"]
    assert [s["parent_span_id"] for s in model_calls] == [root["span_id"]] * 2
    assert model_calls[0]["output"]["tool_calls"] == ["get_telemetry_snapshot"]
    assert model_calls[0]["output"]["text"] == "Checking telemetry first."

    (telemetry,) = [s for s in spans if s["name"] == "get_telemetry_snapshot"]
    assert telemetry["parent_span_id"] == model_calls[0]["span_id"]
    assert telemetry["actor"] == "agent"

    alert = get_alert("ALERT-20")
    assert alert is not None
    assert alert["current_trace_id"] == root["trace_id"]


def test_non_whitelisted_proposal_records_a_denied_guardrail_decision(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-21", machine_id="M-1001", alert_type="coolant_temp_spike")
    client = FakeAnthropicClient(
        [response(tool_use_block("propose_fix", {"fix_id": "replace_engine", "description": "x", "confidence": 0.9}))]
    )

    run_investigation("ALERT-21", client)

    whitelist = [e for e in events_for("ALERT-21") if e["action"] == "guardrail.whitelist"]
    assert [e["status"] for e in whitelist] == ["denied"]


def test_rejecting_starts_a_new_trace_linked_to_the_previous_one(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-22", machine_id="M-1002", alert_type="temperature_drift")
    run_investigation("ALERT-22", _whitelisted_run("ALERT-22"))
    first_trace = get_alert("ALERT-22")["current_trace_id"]  # type: ignore[index]

    reject_fix("ALERT-22", reason="nope")
    client = FakeAnthropicClient(
        [response(tool_use_block("propose_fix", {"fix_id": "restart_sensor", "description": "y", "confidence": 0.6}))]
    )
    run_investigation("ALERT-22", client)

    rounds = round_spans("ALERT-22")
    assert len(rounds) == 2
    assert rounds[0]["trace_id"] == first_trace
    assert rounds[1]["trace_id"] != first_trace
    assert rounds[1]["input"]["previous_trace_id"] == first_trace
    reject = [e for e in events_for("ALERT-22") if e["action"] == "reject"]
    assert reject[0]["span"]["trace_id"] == first_trace


def test_a_step_functions_retry_after_a_crash_actually_reruns(dynamodb_tables: None) -> None:
    """The handler marks the alert failed on every raised attempt. The retry
    used to be refused as a "duplicate" and just report failed; it must
    re-run the investigation instead."""
    _seed(alert_id="ALERT-23", machine_id="M-1002", alert_type="temperature_drift")
    update_alert("ALERT-23", status="failed")

    result = run_investigation("ALERT-23", _whitelisted_run("ALERT-23"))

    assert result["outcome"] == "awaiting_confirmation"
