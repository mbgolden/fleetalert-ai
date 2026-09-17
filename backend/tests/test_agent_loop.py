import pytest

from fleetalert.agent.guardrails import GuardrailViolation
from fleetalert.agent.loop import confirm_fix, execute_fix, reject_fix, run_investigation
from fleetalert.repositories import (
    create_alert,
    get_alert,
    get_audit_trail,
    put_knowledge_base_entry,
    put_machine,
    update_alert,
)
from fleetalert.seed_data import SEED_KNOWLEDGE_BASE, SEED_MACHINES
from tests.fakes import FakeAnthropicClient, response, text_block, tool_use_block


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

    actions = [e["action"] for e in get_audit_trail("ALERT-1")]
    assert actions == [
        "investigation_started",
        "get_telemetry_snapshot",
        "search_knowledge_base",
        "propose_fix",
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

    last_action = get_audit_trail("ALERT-2")[-1]
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

    actions = [e["action"] for e in get_audit_trail("ALERT-4")]
    assert actions[-1] == "execute_fix"


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

    last_action = get_audit_trail("ALERT-4B")[-1]
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


def test_reject_fix_ends_flow_without_executing(dynamodb_tables: None) -> None:
    _seed(alert_id="ALERT-7", machine_id="M-1002", alert_type="temperature_drift")
    update_alert(
        "ALERT-7",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confirmation_token="tok",
    )

    result = reject_fix("ALERT-7", reason="visitor rejected")

    assert result == {"outcome": "rejected", "alert_id": "ALERT-7"}
    assert get_alert("ALERT-7")["status"] == "rejected"  # type: ignore[index]

    last_action = get_audit_trail("ALERT-7")[-1]
    assert last_action["actor"] == "human"
    assert last_action["action"] == "reject"

    with pytest.raises(GuardrailViolation):
        execute_fix("ALERT-7", "send_diagnostic_reset", "tok")
