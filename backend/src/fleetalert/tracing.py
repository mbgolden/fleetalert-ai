"""Structured trace spans -- the Traces table's write path.

One trace per investigation round (a rejection starts a new trace, linked
back through the root span's `previous_trace_id`). Everything that happens
in a round writes a span: the round itself, every model call, every
capability invocation, guardrail decisions, and human confirm/reject.

Spans are append-only (a conditional put refuses to overwrite one); the
only thing that ever deletes them is the demo's Reset Alerts path. See
docs/decisions/ADR-0011.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fleetalert import repositories

# Never persisted into spans: the trace API is public, and these grant (or
# resume) actions.
_REDACTED_KEYS = frozenset({"confirmation_token", "task_token", "step_functions_task_token"})


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[redacted]" if k in _REDACTED_KEYS else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class SpanKind(StrEnum):
    INVESTIGATION = "investigation"  # root span of a round, written when it ends
    MODEL_CALL = "model_call"
    CAPABILITY = "capability"
    DECISION = "decision"  # guardrail / routing decisions made in code
    HUMAN_ACTION = "human_action"
    LIFECYCLE = "lifecycle"  # state-machine events (started, paused, failed)


class SpanStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"  # a failed attempt that is about to be retried
    DENIED = "denied"  # refused by a guardrail before running


class EntryPoint(StrEnum):
    """The contact method that started an investigation."""

    WEB = "web"
    EMAIL = "email"
    AUTONOMOUS = "autonomous"


def new_span_id() -> str:
    # Sorts chronologically as a string, so a trace or alert query returns
    # spans in the order they happened.
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:8]}"


@dataclass
class Tracer:
    alert_id: str
    trace_id: str
    entry_point: str = EntryPoint.WEB
    root_span_id: str = field(default_factory=new_span_id)

    @classmethod
    def start(cls, alert_id: str, entry_point: str = EntryPoint.WEB) -> Tracer:
        return cls(alert_id=alert_id, trace_id=f"trace-{uuid.uuid4().hex}", entry_point=entry_point)

    @classmethod
    def continue_for(cls, alert: dict[str, Any]) -> Tracer:
        """Joins the alert's current round (confirm, reject, execute, ...)."""
        trace_id = alert.get("current_trace_id")
        if not trace_id:
            return cls.start(alert["alert_id"])
        return cls(
            alert_id=alert["alert_id"],
            trace_id=str(trace_id),
            entry_point=str(alert.get("entry_point") or EntryPoint.WEB),
            root_span_id=str(alert.get("current_root_span_id") or new_span_id()),
        )

    def record(
        self,
        *,
        name: str,
        kind: SpanKind,
        actor: str,
        status: SpanStatus = SpanStatus.SUCCESS,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        parent_span_id: str | None = None,
        latency_ms: float | None = None,
        span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        span_id = span_id or new_span_id()
        repositories.put_span(
            {
                "trace_id": self.trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "alert_id": self.alert_id,
                "name": name,
                "kind": str(kind),
                "actor": actor,
                "entry_point": str(self.entry_point),
                "status": str(status),
                "input": redact(input or {}),
                "output": redact(output or {}),
                "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
                "attributes": attributes or {},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return span_id


class Stopwatch:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000
