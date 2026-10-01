"""The investigation queue and its worker (ADR-0024)."""

from __future__ import annotations

import json
from typing import Any

import boto3
import pytest

from fleetalert import loadtest, repositories, workflow
from fleetalert.handlers import investigation_worker_handler as worker
from fleetalert.seed_data import reseed_demo_data


def _record(message_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return {"messageId": message_id, "body": json.dumps(body)}


def _lt_alert(alert_id: str) -> None:
    loadtest.prepare()
    repositories.create_alert(
        {"alert_id": alert_id, "machine_id": loadtest.LOAD_TEST_MACHINE_ID, "status": "open",
         "alert_type": "coolant_temp_spike", "severity": "medium",
         "created_at": loadtest.ALERT_AT.isoformat(), "load_test": True}
    )


class _FakeStepFunctions:
    class exceptions:
        class ExecutionAlreadyExists(Exception):
            pass

    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []

    def start_execution(self, **kwargs: Any) -> dict[str, Any]:
        if any(s["name"] == kwargs["name"] for s in self.started):
            raise self.exceptions.ExecutionAlreadyExists
        self.started.append(kwargs)
        return {}


@pytest.fixture
def fake_sfn(monkeypatch: pytest.MonkeyPatch) -> _FakeStepFunctions:
    fake = _FakeStepFunctions()
    monkeypatch.setattr(workflow, "_stepfunctions", lambda: fake)
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:demo")
    return fake


def test_enqueue_puts_the_request_on_the_queue(dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch) -> None:
    sqs = boto3.client("sqs", region_name="us-east-1")
    url = sqs.create_queue(QueueName="investigations")["QueueUrl"]
    monkeypatch.setenv("INVESTIGATION_QUEUE_URL", url)

    workflow.enqueue_investigation("ALERT-1006", "email")

    [message] = sqs.receive_message(QueueUrl=url)["Messages"]
    assert json.loads(message["Body"]) == {"alert_id": "ALERT-1006", "entry_point": "email"}


def test_a_round_that_routes_to_support_needs_no_execution(dynamodb_tables: None, fake_sfn: _FakeStepFunctions) -> None:
    reseed_demo_data()
    _lt_alert("LT-q-1")

    result = worker.handler({"Records": [_record("m1", {"alert_id": "LT-q-1", "load_test": True})]}, None)

    assert result == {"batchItemFailures": []}
    alert = repositories.get_alert("LT-q-1")
    assert alert is not None and alert["status"] == "routed_to_support"
    assert fake_sfn.started == []


def test_a_proposal_starts_the_execution_at_the_confirmation_wait(
    dynamodb_tables: None, fake_sfn: _FakeStepFunctions, monkeypatch: pytest.MonkeyPatch
) -> None:
    reseed_demo_data()
    repositories.update_alert("ALERT-1006", status="awaiting_confirmation", current_trace_id="trace-abc123")
    monkeypatch.setattr(worker, "run_round", lambda _msg: {"outcome": "awaiting_confirmation", "alert_id": "ALERT-1006"})

    worker.handler({"Records": [_record("m1", {"alert_id": "ALERT-1006", "entry_point": "email"})]}, None)

    [execution] = fake_sfn.started
    assert execution["name"] == "ALERT-1006-trace-abc123"
    assert json.loads(execution["input"]) == {
        "alert_id": "ALERT-1006",
        "entry_point": "email",
        "investigation": {"outcome": "awaiting_confirmation"},
    }


def test_a_duplicate_delivery_does_not_start_a_second_wait(
    dynamodb_tables: None, fake_sfn: _FakeStepFunctions, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SQS delivers at least once; the execution is named after the round."""
    reseed_demo_data()
    repositories.update_alert("ALERT-1006", status="awaiting_confirmation", current_trace_id="trace-abc123")
    monkeypatch.setattr(worker, "run_round", lambda _msg: {"outcome": "awaiting_confirmation", "alert_id": "ALERT-1006"})
    message = {"alert_id": "ALERT-1006", "entry_point": "email"}

    first = worker.handler({"Records": [_record("m1", message)]}, None)
    second = worker.handler({"Records": [_record("m1", message)]}, None)

    assert first == second == {"batchItemFailures": []}
    assert len(fake_sfn.started) == 1


def test_a_failed_round_goes_back_to_the_queue_without_failing_the_batch(
    dynamodb_tables: None, fake_sfn: _FakeStepFunctions, monkeypatch: pytest.MonkeyPatch
) -> None:
    reseed_demo_data()
    _lt_alert("LT-q-ok")

    def explode_for_real_alerts(message: dict[str, Any]) -> dict[str, Any]:
        if message["alert_id"] == "ALERT-9999":
            raise ValueError("No such alert: ALERT-9999")
        return real_run_round(message)

    real_run_round = worker.run_round
    monkeypatch.setattr(worker, "run_round", explode_for_real_alerts)

    result = worker.handler(
        {
            "Records": [
                _record("bad", {"alert_id": "ALERT-9999"}),
                _record("good", {"alert_id": "LT-q-ok", "load_test": True}),
            ]
        },
        None,
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "bad"}]}
    alert = repositories.get_alert("LT-q-ok")
    assert alert is not None and alert["status"] == "routed_to_support"
