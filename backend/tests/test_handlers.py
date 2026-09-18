import json

import boto3
import pytest

from fleetalert.agent.guardrails import GuardrailViolation
from fleetalert.handlers import agent_loop_handler
from fleetalert.handlers.execute_fix_handler import handler as execute_fix_handler
from fleetalert.handlers.wait_for_confirmation_handler import (
    handler as wait_for_confirmation_handler,
)
from fleetalert.repositories import create_alert, get_alert, get_audit_trail, put_machine
from fleetalert.seed_data import SEED_MACHINES
from tests.fakes import FakeAnthropicClient, response, tool_use_block


def _seed_alert(alert_id: str, **overrides: object) -> None:
    alert = {
        "alert_id": alert_id,
        "machine_id": "M-1002",
        "org_id": "org-demo",
        "alert_type": "temperature_drift",
        "severity": "medium",
        "status": "open",
        "created_at": "2026-09-17T10:00:00+00:00",
    }
    alert.update(overrides)
    create_alert(alert)


def test_wait_for_confirmation_handler_persists_task_token(dynamodb_tables: None) -> None:
    _seed_alert("ALERT-1")

    result = wait_for_confirmation_handler(
        {"alert_id": "ALERT-1", "task_token": "sfn-task-token-abc"}, None
    )

    assert result == {"alert_id": "ALERT-1"}
    alert = get_alert("ALERT-1")
    assert alert is not None
    assert alert["step_functions_task_token"] == "sfn-task-token-abc"

    last_action = get_audit_trail("ALERT-1")[-1]
    assert last_action["action"] == "state_machine_paused_for_confirmation"


def test_execute_fix_handler_delegates_to_agent_loop(dynamodb_tables: None) -> None:
    _seed_alert(
        "ALERT-2",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confirmation_token="tok-123",
    )

    result = execute_fix_handler(
        {
            "alert_id": "ALERT-2",
            "fix_id": "send_diagnostic_reset",
            "confirmation_token": "tok-123",
        },
        None,
    )

    assert result == {"outcome": "resolved", "alert_id": "ALERT-2", "fix_id": "send_diagnostic_reset"}
    assert get_alert("ALERT-2")["status"] == "resolved"  # type: ignore[index]


def test_execute_fix_handler_marks_alert_failed_on_exception(dynamodb_tables: None) -> None:
    _seed_alert(
        "ALERT-2B",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confirmation_token="correct-token",
    )

    with pytest.raises(GuardrailViolation):
        execute_fix_handler(
            {"alert_id": "ALERT-2B", "fix_id": "send_diagnostic_reset", "confirmation_token": "wrong"},
            None,
        )

    alert = get_alert("ALERT-2B")
    assert alert is not None
    assert alert["status"] == "failed"

    last_action = get_audit_trail("ALERT-2B")[-1]
    assert last_action["actor"] == "system"
    assert last_action["action"] == "execution_failed"


def test_agent_loop_handler_fetches_secret_and_runs_investigation(
    dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_machine(SEED_MACHINES[1])  # M-1002, refrigeration_unit
    _seed_alert("ALERT-3")

    secretsmanager = boto3.client("secretsmanager", region_name="us-east-1")
    secret = secretsmanager.create_secret(
        Name="fleetalert-anthropic-key",
        SecretString=json.dumps({"anthropic-api-key": "sk-test-key"}),
    )
    monkeypatch.setenv("ANTHROPIC_SECRET_ARN", secret["ARN"])

    fake_client = FakeAnthropicClient(
        [
            response(
                tool_use_block(
                    "propose_fix",
                    {
                        "fix_id": "send_diagnostic_reset",
                        "description": "Matches KB-003.",
                        "confidence": 0.9,
                    },
                )
            )
        ]
    )
    monkeypatch.setattr(agent_loop_handler.anthropic, "Anthropic", lambda api_key: fake_client)

    result = agent_loop_handler.handler({"alert_id": "ALERT-3"}, None)

    assert result["outcome"] == "awaiting_confirmation"
    assert get_alert("ALERT-3")["status"] == "awaiting_confirmation"  # type: ignore[index]


def test_agent_loop_handler_caches_secret_across_invocations(
    dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_loop_handler._secret_cache.clear()
    secretsmanager = boto3.client("secretsmanager", region_name="us-east-1")
    secret = secretsmanager.create_secret(
        Name="cache-test-key",
        SecretString=json.dumps({"anthropic-api-key": "sk-cached"}),
    )
    monkeypatch.setenv("ANTHROPIC_SECRET_ARN", secret["ARN"])

    first = agent_loop_handler._get_anthropic_api_key()
    secretsmanager.update_secret(
        SecretId=secret["ARN"],
        SecretString=json.dumps({"anthropic-api-key": "sk-changed-after-cache"}),
    )
    second = agent_loop_handler._get_anthropic_api_key()

    assert first == second == "sk-cached"
    agent_loop_handler._secret_cache.clear()


def test_agent_loop_handler_marks_alert_failed_on_exception(
    dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # M-1002 deliberately never seeded via put_machine -- run_investigation
    # raises ValueError("No such machine: ...") for a real, unmocked reason.
    _seed_alert("ALERT-5")

    secretsmanager = boto3.client("secretsmanager", region_name="us-east-1")
    secret = secretsmanager.create_secret(
        Name="fail-test-key", SecretString=json.dumps({"anthropic-api-key": "sk-test"})
    )
    monkeypatch.setenv("ANTHROPIC_SECRET_ARN", secret["ARN"])
    monkeypatch.setattr(
        agent_loop_handler.anthropic, "Anthropic", lambda api_key: FakeAnthropicClient([])
    )

    with pytest.raises(ValueError, match="No such machine"):
        agent_loop_handler.handler({"alert_id": "ALERT-5"}, None)

    alert = get_alert("ALERT-5")
    assert alert is not None
    assert alert["status"] == "failed"

    last_action = get_audit_trail("ALERT-5")[-1]
    assert last_action["actor"] == "system"
    assert last_action["action"] == "execution_failed"
