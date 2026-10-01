"""The decision feed: every decision and end state across all alerts.

Built from the same trace spans as the per-alert trace viewer (ADR-0011),
so the feed can't disagree with it. Only spans that record a decision or
an end state become events; model calls and evidence-gathering capability
calls stay in the per-alert trace. See docs/decisions/ADR-0022.
"""

from __future__ import annotations

from typing import Any

from fleetalert import repositories

GUARDRAIL_TITLES = {
    "guardrail.whitelist": "Whitelist check",
    "guardrail.not_previously_rejected": "Repeat-fix check",
    "guardrail.truncated_output": "Cut-off tool call skipped",
    "guardrail.daily_budget": "Daily budget check",
}

ROUTING_REASONS = {
    "fix_not_whitelisted": "proposed fix isn't on the whitelist",
    "fix_already_rejected": "proposed a fix a human already rejected",
    "max_iterations_exceeded": "no fix within 6 loop iterations",
    "rejection_budget_exhausted": "second rejection",
    "confirmation_timed_out": "no human answer within 2 hours",
    "daily_budget_exhausted": "daily demo budget used up",
    "model_refused": "the model declined to continue",
}

DEFAULT_LIMIT = 100


def _event(span: dict[str, Any], *, category: str, title: str, detail: str = "", end_state: str | None = None) -> dict[str, Any]:
    return {
        "timestamp": span["timestamp"],
        "alert_id": span["alert_id"],
        "trace_id": span["trace_id"],
        "entry_point": span.get("entry_point") or "web",
        "category": category,
        "status": span.get("status"),
        "title": title,
        "detail": detail,
        "end_state": end_state,
        "count": 1,
    }


def event_for_span(span: dict[str, Any]) -> dict[str, Any] | None:
    """The feed event a span stands for, or None if it isn't a decision."""
    kind, name, status = span.get("kind"), span.get("name", ""), span.get("status")
    inp = span.get("input") or {}
    out = span.get("output") or {}
    fix_id = str(inp.get("fix_id") or out.get("fix_id") or "")

    if kind == "investigation":
        if out.get("outcome") == "awaiting_confirmation":
            return _event(span, category="outcome", title=f"Proposed {out.get('fix_id') or 'a fix'}", detail="waiting for a human to confirm or reject")
        return None  # routed rounds are reported by their route_to_support span

    if kind == "decision" and name in GUARDRAIL_TITLES:
        verdict = "passed" if status == "success" else "blocked"
        detail = f"{fix_id} · {verdict}" if fix_id else verdict
        if name == "guardrail.daily_budget":
            detail = "round refused before any model call"
        return _event(span, category="guardrail", title=GUARDRAIL_TITLES[name], detail=detail)

    if kind == "decision" and name == "route_to_support":
        reason = str(out.get("reason") or "")
        detail = ROUTING_REASONS.get(reason, reason.replace("_", " "))
        if fix_id:
            detail += f" ({fix_id})"
        return _event(span, category="end_state", title="Routed to support", detail=detail, end_state="routed_to_support")

    if kind == "human_action" and name in ("confirm", "reject"):
        verb = "confirmed" if name == "confirm" else "rejected"
        if status != "success":
            return _event(span, category="human", title=f"{name.capitalize()} refused", detail=str(out.get("error") or ""))
        detail = fix_id
        if name == "reject" and inp.get("reason"):
            detail = f"{fix_id}: “{inp['reason']}”" if fix_id else f"“{inp['reason']}”"
        return _event(span, category="human", title=f"Human {verb}", detail=detail)

    if kind == "capability" and name == "execute_fix" and status == "success":
        return _event(span, category="end_state", title="Fix executed", detail=fix_id, end_state="resolved")

    if kind == "lifecycle" and name == "execution_failed":
        return _event(span, category="end_state", title="Failed", detail=str(out.get("error") or "after retries"), end_state="failed")

    if kind == "lifecycle" and name == "execution_refused":
        return _event(span, category="end_state", title="Execution refused by a guardrail", detail=str(out.get("error") or ""), end_state="refused")

    return None


def events_from_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Events in time order, with repeats merged: a failing Step Functions
    task records one failure span per retry attempt, which is one event."""
    events: list[dict[str, Any]] = []
    for span in sorted(spans, key=lambda s: str(s["timestamp"])):
        event = event_for_span(span)
        if event is None:
            continue
        last = events[-1] if events else None
        if (
            last is not None
            and last["trace_id"] == event["trace_id"]
            and last["title"] == event["title"]
            and last["detail"] == event["detail"]
        ):
            last["count"] += 1
            last["timestamp"] = event["timestamp"]
            continue
        events.append(event)
    return events


def recent_activity(limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Newest first, across every alert. One query per alert: the demo has
    a handful, so this stays cheap without a dedicated index."""
    events: list[dict[str, Any]] = []
    for alert in repositories.list_alerts():
        for event in events_from_spans(repositories.get_spans_for_alert(alert["alert_id"])):
            event["alert_type"] = alert.get("alert_type")
            event["machine_id"] = alert.get("machine_id")
            events.append(event)
    machines = {m: repositories.get_machine(m) for m in {e["machine_id"] for e in events if e.get("machine_id")}}
    for event in events:
        machine = machines.get(event.get("machine_id"))
        event["machine_name"] = machine.get("name") if machine else None
    events.sort(key=lambda e: str(e["timestamp"]), reverse=True)
    return events[:limit]
