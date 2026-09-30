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
from datetime import UTC, datetime
from typing import Any

from fleetalert import intake
from fleetalert.intake import BUSY_STATUSES, KEEP_ROUNDS, REOPENABLE_STATUSES, StartInvestigation
from fleetalert.seed_data import EMAIL_ALERT_ID, SEED_ALERTS

__all__ = ["BUSY_STATUSES", "KEEP_ROUNDS", "REOPENABLE_STATUSES", "deliver_inbound_email"]


def _seed_email_alert() -> dict[str, Any]:
    return copy.deepcopy(next(a for a in SEED_ALERTS if a["alert_id"] == EMAIL_ALERT_ID))


def deliver_inbound_email(start: StartInvestigation, *, trigger: str) -> dict[str, Any]:
    """Returns {"started": bool, "alert_id", "reason"?}. Never raises for a
    busy alert: a skipped delivery is a normal outcome, not an error."""
    email = {**_seed_email_alert()["inbound_email"], "received_at": datetime.now(UTC).isoformat()}
    return intake.reopen_and_start(
        EMAIL_ALERT_ID,
        entry_point="email",
        trigger=trigger,
        fields={"source": "email", "inbound_email": email, "email_trigger": trigger},
        start=start,
        busy_reason="The last email is still being handled",
        initial_alert=_seed_email_alert,
    )
