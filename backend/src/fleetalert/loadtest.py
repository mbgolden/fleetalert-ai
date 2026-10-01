"""Load testing the investigation pipeline, without calling a model.

See docs/decisions/ADR-0023. A load test creates throwaway `LT-` alerts and
starts real Step Functions investigations at a set rate. Everything runs
for real (Lambdas, DynamoDB, the Capabilities Engine, guardrails, traces,
metrics) except the model: those rounds use StubModelClient, a scripted
stand-in that reads telemetry, searches the KB and proposes a fix outside
the whitelist, so every round ends at routed_to_support instead of waiting
two hours for a human.

Safety:
- The stub is only used when the execution input says load_test AND the
  alert id starts with LT- (agent_loop_handler checks both). No public
  route, email or detector run can set either.
- Load-test rounds count against their own usage row, never the demo's
  daily budget (fleetalert.budget scopes).
- LT- alerts are excluded from the alert list and the Activity feed, and
  each run is cleaned up afterwards.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from statistics import quantiles
from types import SimpleNamespace
from typing import Any

from fleetalert import repositories
from fleetalert.autonomous import generate_telemetry

LOAD_TEST_PREFIX = "LT-"
LOAD_TEST_MACHINE_ID = "M-LT"
STUB_MODEL = "load-test-stub"
# Telemetry is generated once, ending at ANCHOR. Every load-test alert is
# stamped an hour earlier, at the anomaly, like a real detector alert, so
# each telemetry query sees readings on both sides of it.
ANCHOR = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)
ALERT_AT = ANCHOR - timedelta(hours=1)
MAX_MINUTES = 12  # the generator Lambda's 15-minute limit, with headroom

LOAD_TEST_MACHINE: dict[str, Any] = {
    "machine_id": LOAD_TEST_MACHINE_ID,
    "machine_type": "diesel_engine",
    "org_id": "org-loadtest",
    "name": "Load-test engine",
    "service_history": [],
}

StartExecution = Callable[[str, str, dict[str, Any]], None]


def is_load_test(alert_id: str) -> bool:
    return alert_id.startswith(LOAD_TEST_PREFIX)


# --- The scripted model --------------------------------------------------

_SCRIPT: list[tuple[str, dict[str, Any]]] = [
    ("get_telemetry_snapshot", {"window_minutes": 60}),
    ("search_knowledge_base", {"symptom_description": "coolant temp spike"}),
    (
        "propose_fix",
        {
            "fix_id": "escalate_to_technician",
            "confidence": 0.5,
            "description": "Load test: telemetry and KB-001/KB-002 read; escalating so the round ends without a human.",
        },
    ),
]


MAX_MODEL_LATENCY_MS = 30_000


class _StubMessages:
    def __init__(self, latency_ms: int, sleep: Callable[[float], None]) -> None:
        self._latency_s = min(max(latency_ms, 0), MAX_MODEL_LATENCY_MS) / 1000
        self._sleep = sleep

    def create(self, **kwargs: Any) -> SimpleNamespace:
        # Stand in for the time a real model call takes. Without it a round
        # is ~0.4 s and concurrency never builds up; a real round holds its
        # Lambda for several seconds per call.
        if self._latency_s:
            self._sleep(self._latency_s)
        turn = sum(1 for m in kwargs["messages"] if m.get("role") == "assistant")
        name, tool_input = _SCRIPT[min(turn, len(_SCRIPT) - 1)]
        return SimpleNamespace(
            stop_reason="tool_use",
            content=[SimpleNamespace(type="tool_use", id=f"lt_{turn}", name=name, input=tool_input)],
            usage=SimpleNamespace(
                input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0
            ),
        )


class StubModelClient:
    """Duck-types the slice of the Anthropic client the loop uses."""

    def __init__(self, latency_ms: int = 0, sleep: Callable[[float], None] = time.sleep) -> None:
        self.messages = _StubMessages(latency_ms, sleep)


# --- Generating load ---------------------------------------------------------


def prepare() -> None:
    """The load-test machine and its telemetry window. Idempotent."""
    repositories.put_machine(LOAD_TEST_MACHINE)
    readings = generate_telemetry("coolant_leak", ANCHOR)
    for reading in readings:
        reading["machine_id"] = LOAD_TEST_MACHINE_ID
        reading.pop("expires_at", None)
    repositories.put_telemetry_readings(readings)


def run(
    label: str,
    *,
    rate_per_hour: int,
    minutes: float,
    start: StartExecution,
    model_latency_ms: int = 0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Create LT- alerts and start their investigations, evenly paced."""
    if rate_per_hour <= 0 or not 0 < minutes <= MAX_MINUTES:
        raise ValueError(f"rate_per_hour must be > 0 and minutes in (0, {MAX_MINUTES}]")
    total = max(1, round(rate_per_hour * minutes / 60))
    # Generating load is not idempotent: a retried invocation would start
    # every investigation again. The first load test did exactly that when
    # a timed-out client retried it (ADR-0023). Claim the label first.
    if not repositories.put_load_test_run(
        label,
        {"status": "running", "requested": total, "rate_per_hour": rate_per_hour, "minutes": minutes,
         "model_latency_ms": model_latency_ms,
         "started_at": datetime.now(UTC).isoformat(), "expires_at": int(time.time()) + 90 * 86400},
        if_new=True,
    ):
        raise ValueError(f"Load-test label {label!r} has already run; refusing to start it twice")
    prepare()
    interval = 3600 / rate_per_hour
    started, errors = 0, Counter[str]()
    t0 = clock()
    for i in range(total):
        alert_id = f"{LOAD_TEST_PREFIX}{label}-{i:05d}"
        repositories.create_alert(
            {
                "alert_id": alert_id,
                "machine_id": LOAD_TEST_MACHINE_ID,
                "org_id": "org-loadtest",
                "alert_type": "coolant_temp_spike",
                "severity": "medium",
                "status": "open",
                "created_at": ALERT_AT.isoformat(),
                "load_test": True,
                "load_test_label": label,
                "load_test_started_at": datetime.now(UTC).isoformat(),
            }
        )
        try:
            start(alert_id, "loadtest", {"load_test": True, "model_latency_ms": model_latency_ms})
            started += 1
        except Exception as exc:  # noqa: BLE001 -- a refused start is a measurement, not a crash
            errors[type(exc).__name__] += 1
        delay = t0 + (i + 1) * interval - clock()
        if delay > 0:
            sleep(delay)
    elapsed = clock() - t0
    summary = {
        "label": label,
        "rate_per_hour": rate_per_hour,
        "minutes": minutes,
        "model_latency_ms": model_latency_ms,
        "requested": total,
        "started": started,
        "start_errors": dict(errors),
        "elapsed_s": round(elapsed, 1),
        "achieved_rate_per_hour": round(started / elapsed * 3600) if elapsed > 0 else None,
    }
    repositories.put_load_test_run(
        label, {**summary, "status": "done", "expires_at": int(time.time()) + 90 * 86400}
    )
    return summary


# --- Measuring ---------------------------------------------------------------


def _ms_between(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000


def _percentiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return {"p50": ordered[0], "p95": ordered[0], "p99": ordered[0], "max": ordered[0]}
    cuts = quantiles(ordered, n=100, method="inclusive")
    return {"p50": round(cuts[49]), "p95": round(cuts[94]), "p99": round(cuts[98]), "max": round(ordered[-1])}


def report(label: str, *, cloudwatch: Callable[[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per-round timings for one run, read back from the traces.

    queue = start_execution until the agent-loop Lambda began the round
    (Step Functions scheduling, Lambda cold starts, retries after throttling);
    processing = the round itself; end_to_end = both.
    """
    # Status first, alerts second. The other way round, a run that finished
    # while the alerts were being read was reported "done" with an alert
    # list from before its end (the second load test lost its last ~25 s
    # of rounds that way).
    run_record = repositories.get_load_test_run(label) or {}
    alerts = repositories.list_load_test_alerts(label)
    queue, processing, end_to_end = [], [], []
    outcomes: Counter[str] = Counter()
    failed = pending = 0
    first_start = last_done = None
    for alert in alerts:
        started_at = str(alert["load_test_started_at"])
        first_start = min(first_start or started_at, started_at)
        spans = repositories.get_spans_for_alert(str(alert["alert_id"]))
        began = next((s for s in spans if s["name"] == "investigation_started"), None)
        root = next((s for s in spans if s["kind"] == "investigation"), None)
        if root is None:
            if any(s["name"] == "execution_failed" for s in spans):
                failed += 1
            else:
                pending += 1
            continue
        outcomes[str((root.get("output") or {}).get("outcome"))] += 1
        if began is not None:
            queue.append(_ms_between(started_at, str(began["timestamp"])))
        processing.append(float(root.get("latency_ms") or 0))
        end_to_end.append(_ms_between(started_at, str(root["timestamp"])))
        last_done = max(last_done or str(root["timestamp"]), str(root["timestamp"]))

    completed = len(processing)
    window_s = _ms_between(first_start, last_done) / 1000 if first_start and last_done else None
    result: dict[str, Any] = {
        "label": label,
        # "running" while the generator is still starting investigations.
        "generation": str(run_record.get("status", "unknown")),
        "run": {
            k: (float(v) if hasattr(v, "is_finite") else v)
            for k, v in run_record.items()
            if k not in ("day", "expires_at", "status")
        },
        "alerts": len(alerts),
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "outcomes": dict(outcomes),
        "throughput_per_hour": round(completed / window_s * 3600) if window_s else None,
        "queue_ms": _percentiles(queue),
        "processing_ms": _percentiles(processing),
        "end_to_end_ms": _percentiles(end_to_end),
        "window": {"first_start": first_start, "last_completion": last_done},
    }
    if cloudwatch and first_start and last_done:
        try:
            result["aws"] = cloudwatch(first_start, last_done)
        except Exception as exc:  # noqa: BLE001 -- AWS metrics are a bonus, not the measurement
            result["aws"] = {"error": f"{type(exc).__name__}: {exc}"}
    result["markdown"] = to_markdown(result)
    return result


def to_markdown(r: dict[str, Any]) -> str:
    def row(name: str, p: dict[str, float] | None) -> str:
        if not p:
            return f"| {name} | — | — | — | — |"
        return f"| {name} | {p['p50']:,.0f} | {p['p95']:,.0f} | {p['p99']:,.0f} | {p['max']:,.0f} |"

    lines = [
        f"### Load test `{r['label']}`",
        "",
        f"{r['completed']:,} of {r['alerts']:,} rounds completed, {r['failed']} failed, {r['pending']} still pending"
        + (f" · simulated model latency {r['run']['model_latency_ms']:,.0f} ms per call" if r.get("run", {}).get("model_latency_ms") else "")
        + (f" · throughput {r['throughput_per_hour']:,}/hour" if r.get("throughput_per_hour") else ""),
        "",
        "| Timing (ms) | p50 | p95 | p99 | max |",
        "|---|---|---|---|---|",
        row("Queue (start → round begins)", r["queue_ms"]),
        row("Processing (the round)", r["processing_ms"]),
        row("End to end", r["end_to_end_ms"]),
        "",
        f"Outcomes: {', '.join(f'{k} ×{v}' for k, v in r['outcomes'].items()) or 'none'}",
    ]
    aws = r.get("aws")
    if aws and "error" not in aws:
        lines += ["", "AWS: " + ", ".join(f"{k} {v:,.0f}" for k, v in aws.items())]
    return "\n".join(lines) + "\n"


def cleanup(label: str | None = None) -> dict[str, Any]:
    """Delete one run's alerts and traces, or (label None) every leftover
    load-test alert, e.g. from a run that failed before cleaning up."""
    alerts = repositories.list_load_test_alerts(label) if label else repositories.list_all_load_test_alerts()
    for alert in alerts:
        repositories.clear_spans_for_alert(str(alert["alert_id"]))
        repositories.delete_alert(str(alert["alert_id"]))
    return {"label": label or "all", "deleted_alerts": len(alerts)}
