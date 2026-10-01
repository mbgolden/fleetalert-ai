"""Daily cost guard (fleetalert.budget) and span-derived metrics
(fleetalert.metrics). ADR-0017."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from fleetalert import budget, metrics
from fleetalert.agent.loop import run_investigation
from fleetalert.handlers import api_handler
from fleetalert.repositories import get_alert
from fleetalert.seed_data import reseed_demo_data
from tests.fakes import FakeAnthropicClient, response, tool_use_block
from tests.trace_helpers import event_names, last_event


def _capped(monkeypatch: pytest.MonkeyPatch, *, rounds: int = 50, cost: float = 1.25) -> None:
    monkeypatch.setenv("FLEETALERT_DAILY_INVESTIGATION_CAP", str(rounds))
    monkeypatch.setenv("FLEETALERT_DAILY_COST_CAP_USD", str(cost))


def test_rounds_are_counted_until_the_cap(dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _capped(monkeypatch, rounds=2)

    assert budget.reserve_round()
    assert budget.reserve_round()
    assert not budget.reserve_round()

    usage = budget.usage()
    assert usage["investigations"] == 2  # the refused round wasn't counted
    assert usage["exhausted"] is True


def test_spend_cap_refuses_new_rounds(dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _capped(monkeypatch, cost=0.10)

    assert budget.reserve_round()
    budget.record_cost(0.06)
    assert budget.reserve_round()  # $0.06 spent, under the cap
    budget.record_cost(0.05)
    assert not budget.reserve_round()  # $0.11 spent
    assert "resets at 00:00 UTC" in budget.exhausted_message()


def _with_usage(block: SimpleNamespace, tokens_in: int, tokens_out: int) -> SimpleNamespace:
    resp = response(block)
    resp.usage = SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out)
    return resp


def test_a_round_records_its_cost(dynamodb_tables: None) -> None:
    reseed_demo_data()
    client = FakeAnthropicClient(
        [
            _with_usage(tool_use_block("get_telemetry_snapshot", {"window_minutes": 60}, "t1"), 2000, 100),
            _with_usage(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "send_diagnostic_reset", "confidence": 0.8, "description": "Matches KB-003."},
                    "t2",
                ),
                3000,
                200,
            ),
        ]
    )

    run_investigation("ALERT-1002", client, model="claude-sonnet-5")

    usage = budget.usage()
    assert usage["investigations"] == 1
    # 5000 in x $2/MTok + 300 out x $10/MTok
    assert usage["cost_usd"] == pytest.approx(0.013)


def test_exhausted_budget_ends_the_round_before_any_model_call(
    dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    reseed_demo_data()
    _capped(monkeypatch, rounds=0)
    client = FakeAnthropicClient([])

    result = run_investigation("ALERT-1002", client)

    assert result == {"outcome": "routed_to_support", "alert_id": "ALERT-1002", "reason": "daily_budget_exhausted"}
    assert client.messages.calls == []
    assert "guardrail.daily_budget" in event_names("ALERT-1002")
    assert last_event("ALERT-1002")["details"]["reason"] == "daily_budget_exhausted"
    alert = get_alert("ALERT-1002")
    assert alert is not None and alert["status"] == "routed_to_support"


def test_api_refuses_investigations_and_emails_once_exhausted(
    dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    reseed_demo_data()
    _capped(monkeypatch, rounds=0)
    started: list[Any] = []
    monkeypatch.setattr(api_handler, "start_investigation", lambda *a: started.append(a))
    monkeypatch.setattr(api_handler, "enqueue_investigation", lambda *a: started.append(a))

    investigate = api_handler.handler(
        {"routeKey": "POST /demo/alerts/{alert_id}/investigate", "pathParameters": {"alert_id": "ALERT-1001"}},
        None,
    )
    email = api_handler.handler({"routeKey": "POST /demo/email"}, None)
    usage = api_handler.handler({"routeKey": "GET /demo/usage"}, None)

    assert investigate["statusCode"] == 429
    assert "budget" in json.loads(investigate["body"])["error"]
    assert email["statusCode"] == 429
    assert json.loads(email["body"])["budget_exhausted"] is True
    assert json.loads(usage["body"])["exhausted"] is True
    assert started == []


def _span(**overrides: Any) -> dict[str, Any]:
    return {"kind": "capability", "name": "search_knowledge_base", "status": "success",
            "entry_point": "web", "latency_ms": 12.5, "attributes": {}, "output": {}, **overrides}


def test_investigation_span_becomes_outcome_cost_and_latency_metrics() -> None:
    [line] = metrics.records_for_span(
        _span(
            kind="investigation",
            name="investigation",
            entry_point="email",
            latency_ms=15000,
            output={"outcome": "awaiting_confirmation"},
            attributes={"estimated_cost_usd": "0.021", "model_calls": 3, "input_tokens": 9000, "output_tokens": 600},
        )
    )
    emf = json.loads(line)
    directive = emf["_aws"]["CloudWatchMetrics"][0]
    assert directive["Namespace"] == "FleetAlert"
    assert directive["Dimensions"] == [[], ["EntryPoint"], ["Outcome"]]
    assert emf["EntryPoint"] == "email" and emf["Outcome"] == "awaiting_confirmation"
    assert emf["Investigations"] == 1
    assert emf["InvestigationCostUSD"] == pytest.approx(0.021)
    assert emf["InvestigationLatencyMs"] == 15000


def test_capability_guardrail_routing_and_human_spans_become_metrics() -> None:
    [cap] = metrics.records_for_span(_span(status="retry"))
    assert json.loads(cap)["Status"] == "retry"

    [block] = metrics.records_for_span(_span(kind="decision", name="guardrail.whitelist", status="failure"))
    assert json.loads(block)["Guardrail"] == "guardrail.whitelist"
    assert metrics.records_for_span(_span(kind="decision", name="guardrail.whitelist", status="success")) == []

    # Routing is also an end state, so it yields a second (AlertEndStates) line.
    routed, end_state = metrics.records_for_span(
        _span(kind="decision", name="route_to_support", output={"reason": "confirmation_timed_out"})
    )
    assert json.loads(routed)["Reason"] == "confirmation_timed_out"
    assert json.loads(end_state)["EndState"] == "routed_to_support"

    [human] = metrics.records_for_span(_span(kind="human_action", name="reject"))
    assert json.loads(human)["Action"] == "reject"

    assert metrics.records_for_span(_span(kind="model_call", name="model_call")) == []


def test_metrics_print_only_when_enabled(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    metrics.emit_for_span(_span())
    assert capsys.readouterr().out == ""

    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "fleetalert-ai-demo-agent-loop")
    metrics.emit_for_span(_span())
    assert '"CapabilityCalls": 1' in capsys.readouterr().out
