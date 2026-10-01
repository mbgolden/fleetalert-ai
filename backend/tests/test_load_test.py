"""Load testing (fleetalert.loadtest, ADR-0023): the scripted model, the
generator, the report, cleanup, and the isolation from the demo."""

from __future__ import annotations

from typing import Any

import pytest

from fleetalert import activity, budget, loadtest, repositories
from fleetalert.handlers import agent_loop_handler, load_test_handler
from fleetalert.seed_data import reseed_demo_data
from tests.trace_helpers import last_event


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _run_inline(alert_id: str, entry_point: str, extra: dict[str, Any]) -> None:
    """Stand-in for Step Functions: run the agent-loop Lambda right away."""
    agent_loop_handler.handler({"alert_id": alert_id, "entry_point": entry_point, **extra}, None)


@pytest.fixture
def no_real_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> str:
        raise AssertionError("a load-test round tried to fetch the real API key")

    monkeypatch.setattr(agent_loop_handler, "_get_anthropic_api_key", refuse)


def test_a_load_test_round_runs_the_real_pipeline_on_the_stub(dynamodb_tables: None, no_real_model: None) -> None:
    reseed_demo_data()
    loadtest.run("t1", rate_per_hour=3600, minutes=1 / 60, start=_run_inline, sleep=lambda _s: None)

    [alert] = repositories.list_load_test_alerts("t1")
    spans = repositories.get_spans_for_alert(alert["alert_id"])
    names = [s["name"] for s in spans]
    assert names.count("model_call") == 3
    assert {"get_telemetry_snapshot", "search_knowledge_base", "propose_fix", "guardrail.whitelist"} <= set(names)
    assert last_event(alert["alert_id"])["details"]["reason"] == "fix_not_whitelisted"
    started = next(s for s in spans if s["name"] == "investigation_started")
    assert started["entry_point"] == "loadtest"
    telemetry = next(s for s in spans if s["name"] == "get_telemetry_snapshot")
    assert len(telemetry["output"]["readings"]) == 13  # the generated window was found


def test_load_test_rounds_never_touch_the_demo_budget(dynamodb_tables: None, no_real_model: None) -> None:
    reseed_demo_data()
    loadtest.run("t2", rate_per_hour=3600, minutes=3 / 60, start=_run_inline, sleep=lambda _s: None)

    assert budget.usage()["investigations"] == 0
    assert int(repositories.get_usage(f"{budget.today()}#loadtest")["investigations"]) == 3


def test_the_stub_is_refused_for_a_real_alert(dynamodb_tables: None, no_real_model: None) -> None:
    reseed_demo_data()

    with pytest.raises(ValueError, match="only allowed for LT- alerts"):
        agent_loop_handler.handler({"alert_id": "ALERT-1001", "load_test": True}, None)

    assert last_event("ALERT-1001")["action"] == "execution_failed"


def test_the_generator_paces_starts_and_counts_refusals(dynamodb_tables: None) -> None:
    clock = _Clock()
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def start(alert_id: str, entry_point: str, extra: dict[str, Any]) -> None:
        calls.append((alert_id, entry_point, extra))
        if len(calls) == 2:
            raise RuntimeError("ExecutionLimitExceeded")

    result = loadtest.run("t3", rate_per_hour=1200, minutes=0.25, start=start, sleep=clock.sleep, clock=clock)

    assert result["requested"] == 5  # 1,200/hour for 15 seconds
    assert result["started"] == 4
    assert result["start_errors"] == {"RuntimeError": 1}
    assert calls[0] == ("LT-t3-00000", "loadtest", {"load_test": True})
    assert clock.slept == pytest.approx([3.0] * 5)  # one start every 3 seconds
    assert len(repositories.list_load_test_alerts("t3")) == 5


def test_the_generator_refuses_a_run_longer_than_the_lambda_can_last(dynamodb_tables: None) -> None:
    with pytest.raises(ValueError):
        loadtest.run("t4", rate_per_hour=1000, minutes=20, start=lambda *_a: None)


def test_report_reads_timings_back_from_the_traces(dynamodb_tables: None, no_real_model: None) -> None:
    reseed_demo_data()
    loadtest.run("t5", rate_per_hour=36000, minutes=0.5 / 60 * 6, start=_run_inline, sleep=lambda _s: None)
    repositories.create_alert(
        {"alert_id": "LT-t5-pending", "machine_id": "M-LT", "status": "open", "created_at": "2026-09-18T06:00:00+00:00",
         "alert_type": "coolant_temp_spike", "severity": "medium", "load_test": True, "load_test_label": "t5",
         "load_test_started_at": "2026-10-01T00:00:00+00:00"}
    )

    result = loadtest.report("t5")

    assert result["alerts"] == 31
    assert result["completed"] == 30
    assert result["pending"] == 1
    assert result["outcomes"] == {"routed_to_support": 30}
    for key in ("queue_ms", "processing_ms", "end_to_end_ms"):
        assert set(result[key]) == {"p50", "p95", "p99", "max"}
    assert "30 of 31 rounds completed" in result["markdown"]


def test_cleanup_removes_a_run_and_its_traces(dynamodb_tables: None, no_real_model: None) -> None:
    reseed_demo_data()
    loadtest.run("t6", rate_per_hour=3600, minutes=2 / 60, start=_run_inline, sleep=lambda _s: None)
    ids = [a["alert_id"] for a in repositories.list_load_test_alerts("t6")]

    assert loadtest.cleanup("t6") == {"label": "t6", "deleted_alerts": 2}
    assert repositories.list_load_test_alerts("t6") == []
    assert all(repositories.get_spans_for_alert(i) == [] for i in ids)


def test_load_test_alerts_stay_out_of_the_demo(dynamodb_tables: None, no_real_model: None) -> None:
    reseed_demo_data()
    loadtest.run("t7", rate_per_hour=3600, minutes=2 / 60, start=_run_inline, sleep=lambda _s: None)

    demo_ids = {a["alert_id"] for a in repositories.list_alerts()}
    assert demo_ids and not any(i.startswith("LT-") for i in demo_ids)
    assert not any(e["alert_id"].startswith("LT-") for e in activity.recent_activity())


def test_scans_follow_every_page() -> None:
    class PagedTable:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def scan(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            if "ExclusiveStartKey" not in kwargs:
                return {"Items": [{"alert_id": "A"}], "LastEvaluatedKey": {"alert_id": "A"}}
            return {"Items": [{"alert_id": "B"}]}

    table = PagedTable()
    assert repositories._scan_all(table) == [{"alert_id": "A"}, {"alert_id": "B"}]
    assert table.calls[1]["ExclusiveStartKey"] == {"alert_id": "A"}


def test_handler_actions(dynamodb_tables: None, no_real_model: None, monkeypatch: pytest.MonkeyPatch) -> None:
    reseed_demo_data()
    monkeypatch.setattr(load_test_handler, "start_investigation", _run_inline)
    monkeypatch.setenv("AGENT_LOOP_FUNCTION_NAME", "fleetalert-ai-demo-agent-loop")
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:demo")

    ran = load_test_handler.handler({"action": "run", "label": "h1", "rate_per_hour": 3600, "minutes": 2 / 60}, None)
    report = load_test_handler.handler({"action": "report", "label": "h1"}, None)
    cleaned = load_test_handler.handler({"action": "cleanup", "label": "h1"}, None)

    assert ran["started"] == 2
    assert report["completed"] == 2
    assert "aws" in report
    assert cleaned["deleted_alerts"] == 2
    with pytest.raises(ValueError):
        load_test_handler.handler({"action": "explode", "label": "h1"}, None)



def test_a_label_can_only_run_once(dynamodb_tables: None) -> None:
    """Generating load isn't idempotent; the first real run was retried by a
    timed-out client and investigated every alert three times."""
    starts: list[str] = []

    def start(alert_id: str, _entry: str, _extra: dict[str, Any]) -> None:
        starts.append(alert_id)

    loadtest.run("once", rate_per_hour=3600, minutes=2 / 60, start=start, sleep=lambda _s: None)
    with pytest.raises(ValueError, match="already run"):
        loadtest.run("once", rate_per_hour=3600, minutes=2 / 60, start=start, sleep=lambda _s: None)

    assert starts == ["LT-once-00000", "LT-once-00001"]
    record = repositories.get_load_test_run("once")
    assert record is not None and record["status"] == "done" and int(record["started"]) == 2


def test_report_says_when_generation_is_finished(dynamodb_tables: None, no_real_model: None) -> None:
    reseed_demo_data()
    loadtest.run("gen", rate_per_hour=3600, minutes=1 / 60, start=_run_inline, sleep=lambda _s: None)

    result = loadtest.report("gen")

    assert result["generation"] == "done"
    assert result["run"]["requested"] == 1


def test_cleanup_all_removes_leftovers_from_every_run(dynamodb_tables: None, no_real_model: None) -> None:
    reseed_demo_data()
    for label in ("left1", "left2"):
        loadtest.run(label, rate_per_hour=3600, minutes=1 / 60, start=_run_inline, sleep=lambda _s: None)

    assert load_test_handler.handler({"action": "cleanup_all"}, None) == {"label": "all", "deleted_alerts": 2}
    assert repositories.list_all_load_test_alerts() == []
    assert len(repositories.list_alerts()) == 6  # the demo alerts are untouched


def test_the_dynamodb_resource_is_reused() -> None:
    """One resource, so one connection pool, per Lambda container."""
    from fleetalert.db import get_dynamodb_resource

    assert get_dynamodb_resource() is get_dynamodb_resource()
