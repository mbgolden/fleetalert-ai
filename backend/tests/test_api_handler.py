import json
from typing import Any

import pytest

from fleetalert.handlers import api_handler
from fleetalert.repositories import (
    create_alert,
    get_alert,
    get_audit_trail,
    put_machine,
    update_alert,
)
from fleetalert.seed_data import SEED_MACHINES


class _FakeStepFunctionsClient:
    def __init__(self) -> None:
        self.started_executions: list[dict[str, Any]] = []
        self.task_successes: list[dict[str, Any]] = []
        self.task_failures: list[dict[str, Any]] = []

    def start_execution(self, **kwargs: Any) -> dict[str, Any]:
        self.started_executions.append(kwargs)
        return {"executionArn": "arn:aws:states:us-east-1:123456789012:execution:test:exec-1"}

    def send_task_success(self, **kwargs: Any) -> dict[str, Any]:
        self.task_successes.append(kwargs)
        return {}

    def send_task_failure(self, **kwargs: Any) -> dict[str, Any]:
        self.task_failures.append(kwargs)
        return {}


@pytest.fixture
def fake_sfn(monkeypatch: pytest.MonkeyPatch) -> _FakeStepFunctionsClient:
    client = _FakeStepFunctionsClient()
    monkeypatch.setattr(api_handler.boto3, "client", lambda *_a, **_k: client)
    return client


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


def test_list_alerts_route(dynamodb_tables: None) -> None:
    put_machine(SEED_MACHINES[1])  # M-1002, refrigeration_unit
    _seed_alert("ALERT-1")
    _seed_alert("ALERT-2")

    resp = api_handler.handler({"routeKey": "GET /demo/alerts"}, None)

    assert resp["statusCode"] == 200
    alerts = json.loads(resp["body"])["alerts"]
    assert {a["alert_id"] for a in alerts} == {"ALERT-1", "ALERT-2"}
    assert all(a["machine_name"] == "Trailer 7 - Reefer Unit" for a in alerts)
    assert all(a["machine_type"] == "refrigeration_unit" for a in alerts)


def test_investigate_route_starts_execution(
    dynamodb_tables: None, fake_sfn: _FakeStepFunctionsClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_alert("ALERT-3")
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:demo")

    resp = api_handler.handler(
        {
            "routeKey": "POST /demo/alerts/{alert_id}/investigate",
            "pathParameters": {"alert_id": "ALERT-3"},
        },
        None,
    )

    assert resp["statusCode"] == 202
    assert len(fake_sfn.started_executions) == 1
    call = fake_sfn.started_executions[0]
    assert call["stateMachineArn"] == "arn:aws:states:us-east-1:123456789012:stateMachine:demo"
    assert json.loads(call["input"]) == {"alert_id": "ALERT-3"}


def test_get_status_route(dynamodb_tables: None) -> None:
    _seed_alert(
        "ALERT-4",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confidence=0.9,
        root_cause_summary="Matches KB-003.",
        confirmation_token="tok-abc",
    )

    resp = api_handler.handler(
        {"routeKey": "GET /demo/alerts/{alert_id}/status", "pathParameters": {"alert_id": "ALERT-4"}},
        None,
    )

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body == {
        "alert_id": "ALERT-4",
        "status": "awaiting_confirmation",
        "proposed_fix": "send_diagnostic_reset",
        "confidence": "0.9",
        "root_cause_summary": "Matches KB-003.",
        "confirmation_token": "tok-abc",
    }


def test_get_status_route_missing_alert(dynamodb_tables: None) -> None:
    resp = api_handler.handler(
        {"routeKey": "GET /demo/alerts/{alert_id}/status", "pathParameters": {"alert_id": "nope"}},
        None,
    )

    assert resp["statusCode"] == 404


def test_confirm_route_sends_task_success_when_task_token_present(
    dynamodb_tables: None, fake_sfn: _FakeStepFunctionsClient
) -> None:
    _seed_alert(
        "ALERT-5",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confirmation_token="tok-abc",
        step_functions_task_token="sfn-token-xyz",
    )

    resp = api_handler.handler(
        {
            "routeKey": "POST /demo/alerts/{alert_id}/confirm",
            "pathParameters": {"alert_id": "ALERT-5"},
            "body": json.dumps({"confirmation_token": "tok-abc"}),
        },
        None,
    )

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"alert_id": "ALERT-5", "outcome": "confirmed"}
    assert len(fake_sfn.task_successes) == 1
    call = fake_sfn.task_successes[0]
    assert call["taskToken"] == "sfn-token-xyz"
    assert json.loads(call["output"]) == {
        "alert_id": "ALERT-5",
        "fix_id": "send_diagnostic_reset",
        "confirmation_token": "tok-abc",
    }

    last_action = get_audit_trail("ALERT-5")[-1]
    assert last_action["action"] == "confirm"


def test_confirm_route_rejects_wrong_token(
    dynamodb_tables: None, fake_sfn: _FakeStepFunctionsClient
) -> None:
    _seed_alert(
        "ALERT-6",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confirmation_token="tok-abc",
        step_functions_task_token="sfn-token-xyz",
    )

    resp = api_handler.handler(
        {
            "routeKey": "POST /demo/alerts/{alert_id}/confirm",
            "pathParameters": {"alert_id": "ALERT-6"},
            "body": json.dumps({"confirmation_token": "wrong"}),
        },
        None,
    )

    assert resp["statusCode"] == 403
    assert fake_sfn.task_successes == []


def test_reject_route_sends_task_failure(dynamodb_tables: None, fake_sfn: _FakeStepFunctionsClient) -> None:
    _seed_alert(
        "ALERT-7",
        status="awaiting_confirmation",
        proposed_fix="send_diagnostic_reset",
        confirmation_token="tok-abc",
        step_functions_task_token="sfn-token-xyz",
    )

    resp = api_handler.handler(
        {
            "routeKey": "POST /demo/alerts/{alert_id}/reject",
            "pathParameters": {"alert_id": "ALERT-7"},
            "body": json.dumps({"reason": "visitor rejected"}),
        },
        None,
    )

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"outcome": "rejected", "alert_id": "ALERT-7"}
    assert get_alert("ALERT-7")["status"] == "rejected"  # type: ignore[index]

    assert len(fake_sfn.task_failures) == 1
    call = fake_sfn.task_failures[0]
    assert call["taskToken"] == "sfn-token-xyz"
    assert call["error"] == "Rejected"
    assert call["cause"] == "visitor rejected"


def test_audit_route(dynamodb_tables: None) -> None:
    _seed_alert("ALERT-8")
    update_alert("ALERT-8", status="investigating")

    resp = api_handler.handler(
        {"routeKey": "GET /demo/alerts/{alert_id}/audit", "pathParameters": {"alert_id": "ALERT-8"}},
        None,
    )

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"audit_trail": []}


def test_unknown_route_returns_404(dynamodb_tables: None) -> None:
    resp = api_handler.handler({"routeKey": "DELETE /demo/alerts"}, None)
    assert resp["statusCode"] == 404
