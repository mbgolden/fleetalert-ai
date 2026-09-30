"""The simulated inbound-email entry point. See docs/decisions/ADR-0016.

Every 4 hours (EventBridge -> email_trigger_handler), or when a visitor
presses "Simulate inbound email" (POST /demo/email), the seeded email
"arrives": ALERT-1006 is reopened with a fresh received_at and an
investigation starts with entry_point="email". Same state machine, same
loop, same guardrails as the web entry point; only the trigger differs.

The email body reaches the model as untrusted data (see
fleetalert.agent.loop), and nothing in it can skip human confirmation:
the loop never holds the executes_action tier.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fleetalert import repositories
from fleetalert.logging_config import alert_logger
from fleetalert.repositories import ConcurrentUpdateError
from fleetalert.seed_data import EMAIL_ALERT_ID, SEED_ALERTS

# An investigation of the previous email is still running or waiting on a
# human (for at most 2 hours; see the WaitForConfirmation timeout).
BUSY_STATUSES = ("queued", "investigating", "awaiting_confirmation")
# Anything else can be reopened by a new email.
REOPENABLE_STATUSES = ("open", "resolved", "routed_to_support", "failed")
# Rounds of trace history kept on the email alert, including the new one,
# so web and email rounds can sit side by side without growing forever.
KEEP_ROUNDS = 3

StartInvestigation = Callable[[str, str], None]


def _seed_email_alert() -> dict[str, Any]:
    return copy.deepcopy(next(a for a in SEED_ALERTS if a["alert_id"] == EMAIL_ALERT_ID))


def deliver_inbound_email(start: StartInvestigation, *, trigger: str) -> dict[str, Any]:
    """Returns {"started": bool, "alert_id", "reason"?}. Never raises for a
    busy alert: a skipped delivery is a normal outcome, not an error."""
    log = alert_logger(__name__, EMAIL_ALERT_ID)
    alert = repositories.get_alert(EMAIL_ALERT_ID)
    if alert is None:
        repositories.create_alert(_seed_email_alert())
        alert = repositories.get_alert(EMAIL_ALERT_ID) or {}

    if alert.get("status") in BUSY_STATUSES:
        log.info("inbound email (%s) held: alert is %s", trigger, alert.get("status"))
        return {
            "started": False,
            "alert_id": EMAIL_ALERT_ID,
            "reason": f"The last email is still being handled (status: {alert.get('status')}).",
        }

    email = {**_seed_email_alert()["inbound_email"], "received_at": datetime.now(UTC).isoformat()}
    try:
        # Claim the alert atomically: of two simultaneous deliveries, only
        # one moves it out of a reopenable status.
        repositories.update_alert_if_current(
            EMAIL_ALERT_ID,
            expected_status=list(REOPENABLE_STATUSES),
            status="queued",
            source="email",
            inbound_email=email,
            email_trigger=trigger,
            proposed_fix=None,
            confidence=None,
            root_cause_summary=None,
            confirmation_token=None,
            step_functions_task_token=None,
            rejected_fixes=[],
        )
    except ConcurrentUpdateError:
        log.info("inbound email (%s) lost a race with another delivery", trigger)
        return {"started": False, "alert_id": EMAIL_ALERT_ID, "reason": "Another email just arrived."}

    repositories.prune_traces_for_alert(EMAIL_ALERT_ID, keep=KEEP_ROUNDS - 1)
    try:
        start(EMAIL_ALERT_ID, "email")
    except Exception:
        # Don't leave the alert claimed forever if the execution never started.
        repositories.update_alert(EMAIL_ALERT_ID, status="failed")
        raise
    log.info("inbound email (%s) delivered, investigation started", trigger)
    return {"started": True, "alert_id": EMAIL_ALERT_ID}
