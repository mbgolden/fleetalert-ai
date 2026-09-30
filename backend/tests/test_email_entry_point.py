"""The email entry point: delivery, the untrusted-email framing, the
confirmation timeout, and the handlers/route that trigger them."""

from __future__ import annotations

import json
from typing import Any

import pytest

from fleetalert import email_intake
from fleetalert.agent.loop import expire_confirmation, run_investigation
from fleetalert.handlers import api_handler, confirmation_timeout_handler, email_trigger_handler
from fleetalert.repositories import get_alert, get_spans_for_alert, update_alert
from fleetalert.seed_data import EMAIL_ALERT_ID, reseed_demo_data
from fleetalert.tracing import SpanKind, Tracer
from tests.fakes import FakeAnthropicClient, response, tool_use_block
from tests.trace_helpers import last_event


class _Starts:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def __call__(self, alert_id: str, entry_point: str) -> None:
        if self.fail:
            raise RuntimeError("StartExecution failed")
        self.calls.append((alert_id, entry_point))


def _add_rounds(n: int) -> list[str]:
    trace_ids = []
    for _ in range(n):
        tracer = Tracer.start(EMAIL_ALERT_ID)
        tracer.record(name="investigation_started", kind=SpanKind.LIFECYCLE, actor="system")
        trace_ids.append(tracer.trace_id)
    return trace_ids


def test_delivery_reopens_the_email_alert_and_starts_an_email_investigation(dynamodb_tables: None) -> None:
    reseed_demo_data()
    update_alert(EMAIL_ALERT_ID, status="resolved", proposed_fix="restart_sensor", rejected_fixes=[{"fix_id": "x"}])
    starts = _Starts()

    result = email_intake.deliver_inbound_email(starts, trigger="button")

    assert result == {"started": True, "alert_id": EMAIL_ALERT_ID}
    assert starts.calls == [(EMAIL_ALERT_ID, "email")]
    alert = get_alert(EMAIL_ALERT_ID)
    assert alert is not None
    assert alert["status"] == "queued"
    assert alert["proposed_fix"] is None
    assert alert["rejected_fixes"] == []
    assert alert["email_trigger"] == "button"
    assert alert["inbound_email"]["received_at"] != "2026-09-16T12:04:00+00:00"  # stamped on arrival


@pytest.mark.parametrize("status", email_intake.BUSY_STATUSES)
def test_delivery_is_held_while_the_last_email_is_being_handled(dynamodb_tables: None, status: str) -> None:
    reseed_demo_data()
    update_alert(EMAIL_ALERT_ID, status=status)
    starts = _Starts()

    result = email_intake.deliver_inbound_email(starts, trigger="schedule")

    assert result["started"] is False
    assert status in result["reason"]
    assert starts.calls == []


def test_a_failed_start_does_not_leave_the_alert_claimed(dynamodb_tables: None) -> None:
    reseed_demo_data()

    with pytest.raises(RuntimeError):
        email_intake.deliver_inbound_email(_Starts(fail=True), trigger="schedule")

    alert = get_alert(EMAIL_ALERT_ID)
    assert alert is not None and alert["status"] == "failed"


def test_delivery_keeps_only_the_most_recent_rounds(dynamodb_tables: None) -> None:
    reseed_demo_data()
    trace_ids = _add_rounds(4)

    email_intake.deliver_inbound_email(_Starts(), trigger="schedule")

    kept = {s["trace_id"] for s in get_spans_for_alert(EMAIL_ALERT_ID)}
    assert kept == set(trace_ids[-(email_intake.KEEP_ROUNDS - 1) :])


def test_the_email_reaches_the_model_as_untrusted_data_and_cannot_skip_confirmation(
    dynamodb_tables: None,
) -> None:
    reseed_demo_data()
    email_intake.deliver_inbound_email(_Starts(), trigger="schedule")
    client = FakeAnthropicClient(
        [
            response(tool_use_block("get_telemetry_snapshot", {"window_minutes": 60}, "t1")),
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "restart_sensor", "confidence": 0.8, "description": "One 121 C spike, KB-001."},
                    "t2",
                )
            ),
        ]
    )

    result = run_investigation(EMAIL_ALERT_ID, client, entry_point="email")

    opening = client.messages.calls[0]["messages"][0]["content"]
    assert "<inbound_email>" in opening
    assert "untrusted" in opening
    assert "just go ahead and apply the fix" in opening
    # The email asked to skip approval; the outcome still waits on a human.
    assert result["outcome"] == "awaiting_confirmation"
    started = next(s for s in get_spans_for_alert(EMAIL_ALERT_ID) if s["name"] == "investigation_started")
    assert started["entry_point"] == "email"


def test_confirmation_timeout_routes_to_support(dynamodb_tables: None) -> None:
    reseed_demo_data()
    update_alert(EMAIL_ALERT_ID, status="awaiting_confirmation", proposed_fix="restart_sensor", confirmation_token="tok")

    result = confirmation_timeout_handler.handler({"alert_id": EMAIL_ALERT_ID}, None)

    assert result["outcome"] == "routed_to_support"
    alert = get_alert(EMAIL_ALERT_ID)
    assert alert is not None
    assert alert["status"] == "routed_to_support"
    assert alert["confirmation_token"] is None
    event = last_event(EMAIL_ALERT_ID)
    assert event["action"] == "route_to_support"
    assert event["details"]["reason"] == "confirmation_timed_out"


def test_confirmation_timeout_is_a_no_op_once_a_human_answered(dynamodb_tables: None) -> None:
    reseed_demo_data()
    update_alert(EMAIL_ALERT_ID, status="resolved")

    result = expire_confirmation(EMAIL_ALERT_ID)

    assert result["outcome"] == "resolved"
    alert = get_alert(EMAIL_ALERT_ID)
    assert alert is not None and alert["status"] == "resolved"


def test_scheduled_trigger_handler_delivers(dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch) -> None:
    reseed_demo_data()
    starts = _Starts()
    monkeypatch.setattr(email_trigger_handler, "start_investigation", starts)

    result = email_trigger_handler.handler({}, None)

    assert result["started"] is True
    assert starts.calls == [(EMAIL_ALERT_ID, "email")]
    alert = get_alert(EMAIL_ALERT_ID)
    assert alert is not None and alert["email_trigger"] == "schedule"


def test_email_route_starts_then_reports_busy(dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch) -> None:
    reseed_demo_data()
    starts = _Starts()
    monkeypatch.setattr(api_handler, "start_investigation", starts)

    first = api_handler.handler({"routeKey": "POST /demo/email"}, None)
    second = api_handler.handler({"routeKey": "POST /demo/email"}, None)

    assert first["statusCode"] == 202
    assert second["statusCode"] == 409
    body: dict[str, Any] = json.loads(second["body"])
    assert body["started"] is False
    assert starts.calls == [(EMAIL_ALERT_ID, "email")]


def test_status_route_exposes_the_email(dynamodb_tables: None) -> None:
    reseed_demo_data()

    resp = api_handler.handler(
        {"routeKey": "GET /demo/alerts/{alert_id}/status", "pathParameters": {"alert_id": EMAIL_ALERT_ID}},
        None,
    )

    body = json.loads(resp["body"])
    assert body["source"] == "email"
    assert body["inbound_email"]["subject"] == "Truck 22 coolant warning on the highway"
