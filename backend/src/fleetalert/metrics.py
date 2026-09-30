"""CloudWatch metrics derived from trace spans. See docs/decisions/ADR-0017.

Spans are the source of truth; each one written also becomes metric data
points in CloudWatch Embedded Metric Format: a JSON log line that
CloudWatch Logs turns into metrics, with no PutMetricData calls and no
extra IAM. Dimensions stay low-cardinality (entry point, outcome,
capability, status), never alert or trace ids.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fleetalert import config

NAMESPACE = "FleetAlert"


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _emf(dimensions: dict[str, str], dimension_sets: list[list[str]], metrics: dict[str, tuple[float, str]]) -> str:
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": NAMESPACE,
                        "Dimensions": dimension_sets,
                        "Metrics": [{"Name": name, "Unit": unit} for name, (_, unit) in metrics.items()],
                    }
                ],
            },
            **dimensions,
            **{name: value for name, (value, _) in metrics.items()},
        }
    )


def records_for_span(span: dict[str, Any]) -> list[str]:
    """The EMF lines a span produces (possibly none). Pure, for testing."""
    kind, name, status = span.get("kind"), span.get("name", ""), span.get("status")
    attrs = span.get("attributes") or {}
    output = span.get("output") or {}
    entry = str(span.get("entry_point") or "web")
    latency = _num(span.get("latency_ms"))
    lines: list[str] = []

    if kind == "investigation":
        outcome = str(output.get("outcome") or "unknown")
        lines.append(
            _emf(
                {"EntryPoint": entry, "Outcome": outcome},
                [[], ["EntryPoint"], ["Outcome"]],
                {
                    "Investigations": (1, "Count"),
                    "InvestigationCostUSD": (_num(attrs.get("estimated_cost_usd")), "None"),
                    "InvestigationLatencyMs": (latency, "Milliseconds"),
                    "ModelCalls": (_num(attrs.get("model_calls")), "Count"),
                    "InputTokens": (_num(attrs.get("input_tokens")), "Count"),
                    "OutputTokens": (_num(attrs.get("output_tokens")), "Count"),
                },
            )
        )
    elif kind == "capability":
        lines.append(
            _emf(
                {"Capability": name, "Status": str(status)},
                [["Status"], ["Capability", "Status"]],
                {"CapabilityCalls": (1, "Count"), "CapabilityLatencyMs": (latency, "Milliseconds")},
            )
        )
    elif kind == "decision" and name.startswith("guardrail.") and status != "success":
        lines.append(_emf({"Guardrail": name}, [[], ["Guardrail"]], {"GuardrailBlocks": (1, "Count")}))
    elif kind == "decision" and name == "route_to_support":
        reason = str(output.get("reason") or "unknown")
        lines.append(_emf({"Reason": reason}, [[], ["Reason"]], {"RoutedToSupport": (1, "Count")}))
    elif kind == "human_action" and status == "success":
        lines.append(_emf({"Action": name}, [["Action"]], {"HumanActions": (1, "Count")}))
    elif kind == "lifecycle" and name == "execution_failed":
        lines.append(_emf({}, [[]], {"ExecutionFailures": (1, "Count")}))
    elif kind == "lifecycle" and name == "execution_refused":
        lines.append(_emf({}, [[]], {"ExecutionRefusals": (1, "Count")}))
    return lines


def emit_detector_run(result: str) -> None:
    """One telemetry detector run: the alert type raised, or "normal"."""
    if config.metrics_enabled():
        print(_emf({"Result": result}, [[], ["Result"]], {"DetectorRuns": (1, "Count")}), flush=True)


def emit_for_span(span: dict[str, Any]) -> None:
    if not config.metrics_enabled():
        return
    for line in records_for_span(span):
        # Straight to stdout: EMF must be the raw log line, not wrapped by
        # the JSON log formatter.
        print(line, flush=True)
