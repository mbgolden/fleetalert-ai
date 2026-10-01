"""The decision feed (fleetalert.activity) and the end-state metric. ADR-0022."""

from __future__ import annotations

import json
from typing import Any

import pytest

from fleetalert import activity, metrics
from fleetalert.agent.loop import confirm_fix, execute_fix, reject_fix, run_investigation
from fleetalert.handlers import api_handler
from fleetalert.seed_data import reseed_demo_data
from fleetalert.tracing import SpanKind, SpanStatus, Tracer
from tests.fakes import FakeAnthropicClient, response, tool_use_block


def _propose(fix_id: str) -> FakeAnthropicClient:
    return FakeAnthropicClient(
        [
            response(tool_use_block("get_telemetry_snapshot", {"window_minutes": 60}, "t1")),
            response(
                tool_use_block(
                    "propose_fix", {"fix_id": fix_id, "confidence": 0.8, "description": "Matches KB-003."}, "t2"
                )
            ),
        ]
    )


def _titles(events: list[dict[str, Any]]) -> list[str]:
    return [e["title"] for e in events]


def test_a_confirmed_fix_reads_as_proposal_check_confirm_resolved(dynamodb_tables: None) -> None:
    reseed_demo_data()
    proposal = run_investigation("ALERT-1002", _propose("send_diagnostic_reset"))
    confirm_fix("ALERT-1002", proposal["confirmation_token"])
    execute_fix("ALERT-1002", "send_diagnostic_reset", proposal["confirmation_token"])

    events = activity.recent_activity()

    assert _titles(events) == ["Fix executed", "Human confirmed", "Proposed send_diagnostic_reset", "Whitelist check"]
    resolved = events[0]
    assert resolved["end_state"] == "resolved"
    assert resolved["category"] == "end_state"
    assert resolved["alert_id"] == "ALERT-1002"
    assert resolved["machine_name"] == "Trailer 7 - Reefer Unit"
    assert events[-1]["detail"] == "send_diagnostic_reset · passed"


def test_routing_explains_its_reason(dynamodb_tables: None) -> None:
    reseed_demo_data()
    run_investigation("ALERT-1005", _propose("escalate_to_technician"))

    events = activity.recent_activity()

    routed = events[0]
    assert routed["title"] == "Routed to support"
    assert routed["end_state"] == "routed_to_support"
    assert routed["detail"] == "proposed fix isn't on the whitelist (escalate_to_technician)"
    assert events[1]["title"] == "Whitelist check" and events[1]["detail"].endswith("blocked")


def test_a_rejection_shows_the_reason(dynamodb_tables: None) -> None:
    reseed_demo_data()
    run_investigation("ALERT-1003", _propose("schedule_service_visit"))
    reject_fix("ALERT-1003", reason="Bay booked for two weeks")

    rejected = activity.recent_activity()[0]

    assert rejected["title"] == "Human rejected"
    assert rejected["detail"] == "schedule_service_visit: “Bay booked for two weeks”"


def test_retry_failures_merge_into_one_event(dynamodb_tables: None) -> None:
    reseed_demo_data()
    tracer = Tracer.start("ALERT-1001")
    for _ in range(5):
        tracer.record(
            name="execution_failed",
            kind=SpanKind.LIFECYCLE,
            actor="system",
            status=SpanStatus.FAILURE,
            output={"error": "ValueError: No such machine: M-1004"},
        )

    [failed] = activity.recent_activity()

    assert failed["title"] == "Failed"
    assert failed["count"] == 5
    assert failed["detail"] == "ValueError: No such machine: M-1004"


def test_model_calls_and_evidence_reads_stay_out_of_the_feed() -> None:
    span = {"kind": "model_call", "name": "model_call", "status": "success", "timestamp": "t", "alert_id": "A", "trace_id": "x"}
    assert activity.event_for_span(span) is None
    span = {**span, "kind": "capability", "name": "get_telemetry_snapshot"}
    assert activity.event_for_span(span) is None


def test_activity_route(dynamodb_tables: None) -> None:
    reseed_demo_data()
    run_investigation("ALERT-1005", _propose("escalate_to_technician"))

    resp = api_handler.handler({"routeKey": "GET /demo/activity"}, None)

    assert resp["statusCode"] == 200
    events = json.loads(resp["body"])["events"]
    assert events[0]["title"] == "Routed to support"


@pytest.mark.parametrize(
    ("kind", "name", "status", "end_state"),
    [
        ("capability", "execute_fix", "success", "resolved"),
        ("decision", "route_to_support", "success", "routed_to_support"),
        ("lifecycle", "execution_refused", "denied", "refused"),
        ("lifecycle", "execution_failed", "failure", None),  # counted from Step Functions instead
        ("capability", "execute_fix", "failure", None),
        ("decision", "guardrail.whitelist", "failure", None),
    ],
)
def test_end_state_metric(kind: str, name: str, status: str, end_state: str | None) -> None:
    span = {"kind": kind, "name": name, "status": status, "entry_point": "email", "output": {}, "attributes": {}}
    lines = [json.loads(line) for line in metrics.records_for_span(span)]
    end_lines = [line for line in lines if "AlertEndStates" in line]
    if end_state is None:
        assert end_lines == []
    else:
        [line] = end_lines
        assert line["EndState"] == end_state
        assert line["EntryPoint"] == "email"
        assert line["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[], ["EndState"]]
