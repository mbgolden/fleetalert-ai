"""Reopening a recurring alert and starting an investigation for it.

Shared by the entry points whose alert comes around again: the inbound
email (fleetalert.email_intake, ADR-0016) and the telemetry detector
(fleetalert.autonomous, ADR-0020). Each claims its alert atomically, keeps
a bounded trace history, and starts the same Step Functions execution as
the web UI, tagged with its own entry_point.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fleetalert import budget, repositories
from fleetalert.logging_config import alert_logger
from fleetalert.repositories import ConcurrentUpdateError

# An investigation of the previous occurrence is still running or waiting on
# a human (for at most 2 hours; see the WaitForConfirmation timeout).
BUSY_STATUSES = ("queued", "investigating", "awaiting_confirmation")
# Anything else can be reopened by a new occurrence.
REOPENABLE_STATUSES = ("open", "resolved", "routed_to_support", "failed")
# Rounds of trace history kept per recurring alert, including the new one.
KEEP_ROUNDS = 3

StartInvestigation = Callable[[str, str], None]

# Fields a previous occurrence may have left behind.
_CLEARED_FIELDS: dict[str, Any] = {
    "proposed_fix": None,
    "confidence": None,
    "root_cause_summary": None,
    # Clearing token fields, not credentials: bandit misreads the key names.
    "confirmation_token": None,  # nosec B105
    "step_functions_task_token": None,  # nosec B105
    "rejected_fixes": [],
}


def reopen_and_start(
    alert_id: str,
    *,
    entry_point: str,
    trigger: str,
    fields: dict[str, Any],
    start: StartInvestigation,
    busy_reason: str,
    initial_alert: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Returns {"started": bool, "alert_id", "reason"?, "budget_exhausted"?}.

    A busy alert, an exhausted daily budget or a lost race are normal
    outcomes, reported rather than raised. `initial_alert` builds the alert
    the first time it's ever needed.
    """
    log = alert_logger(__name__, alert_id)
    alert = repositories.get_alert(alert_id)
    if alert is None:
        repositories.create_alert(initial_alert())
        alert = repositories.get_alert(alert_id) or {}

    if alert.get("status") in BUSY_STATUSES:
        log.info("%s (%s) held: alert is %s", entry_point, trigger, alert.get("status"))
        return {
            "started": False,
            "alert_id": alert_id,
            "reason": f"{busy_reason} (status: {alert.get('status')}).",
        }

    if budget.usage()["exhausted"]:
        log.info("%s (%s) held: daily budget exhausted", entry_point, trigger)
        return {
            "started": False,
            "alert_id": alert_id,
            "budget_exhausted": True,
            "reason": budget.exhausted_message(),
        }

    try:
        # Of two simultaneous triggers, only one moves the alert out of a
        # reopenable status.
        repositories.update_alert_if_current(
            alert_id,
            expected_status=list(REOPENABLE_STATUSES),
            status="queued",
            **_CLEARED_FIELDS,
            **fields,
        )
    except ConcurrentUpdateError:
        log.info("%s (%s) lost a race with another trigger", entry_point, trigger)
        return {"started": False, "alert_id": alert_id, "reason": "Another trigger just claimed this alert."}

    repositories.prune_traces_for_alert(alert_id, keep=KEEP_ROUNDS - 1)
    try:
        start(alert_id, entry_point)
    except Exception:
        # Don't leave the alert claimed forever if the execution never started.
        repositories.update_alert(alert_id, status="failed")
        raise
    log.info("%s (%s): investigation started", entry_point, trigger)
    return {"started": True, "alert_id": alert_id}
