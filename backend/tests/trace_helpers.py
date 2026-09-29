"""Test helpers for reading the Traces table the way the old audit tests did."""

from __future__ import annotations

from typing import Any

from fleetalert.repositories import get_spans_for_alert

EVENT_KINDS = ("lifecycle", "capability", "decision", "human_action")


def events(alert_id: str) -> list[dict[str, Any]]:
    """Spans that represent something happening (no model calls, no round
    roots), each flattened to {action, actor, status, details}."""
    return [
        {
            "action": s["name"],
            "actor": s["actor"],
            "status": s["status"],
            "kind": s["kind"],
            "details": {**(s.get("input") or {}), **(s.get("output") or {})},
            "span": s,
        }
        for s in get_spans_for_alert(alert_id)
        if s["kind"] in EVENT_KINDS
    ]


def event_names(alert_id: str) -> list[str]:
    return [e["action"] for e in events(alert_id)]


def last_event(alert_id: str) -> dict[str, Any]:
    return events(alert_id)[-1]


def round_spans(alert_id: str) -> list[dict[str, Any]]:
    return [s for s in get_spans_for_alert(alert_id) if s["kind"] == "investigation"]
