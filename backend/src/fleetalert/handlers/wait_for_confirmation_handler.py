"""Lambda entrypoint for the Step Functions 'WaitForConfirmation' task.

Uses the waitForTaskToken service integration -- Step Functions pauses the
state machine on this task until something calls SendTaskSuccess or
SendTaskFailure with the token, regardless of what this handler itself
returns. Its only job is to persist that token on the alert so the confirm/reject API handlers can find it later; it does not
resolve the wait itself.
"""

from __future__ import annotations

from typing import Any

from fleetalert import repositories
from fleetalert.logging_config import alert_logger, configure_logging
from fleetalert.tracing import SpanKind, Tracer

configure_logging()


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    alert_id = event["alert_id"]
    log = alert_logger(__name__, alert_id)
    log.info("state machine paused, persisting task token")
    repositories.update_alert(alert_id, step_functions_task_token=event["task_token"])
    alert = repositories.get_alert(alert_id)
    if alert is not None:
        tracer = Tracer.continue_for(alert)
        tracer.record(
            name="awaiting_human_confirmation",
            kind=SpanKind.LIFECYCLE,
            actor="system",
            parent_span_id=tracer.root_span_id,
        )
    return {"alert_id": alert_id}
