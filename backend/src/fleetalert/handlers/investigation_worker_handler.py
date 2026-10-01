"""Lambda entrypoint for the investigation queue (ADR-0024).

SQS invokes this with a fixed maximum concurrency. Each message is one
alert to investigate: the worker runs the round itself and, if the round
ends in a proposal, starts the Step Functions execution at the
human-confirmation wait. Rounds that route to support need no execution.

A message whose round raises goes back to the queue (reported as a batch
item failure); after three receives SQS moves it to the dead-letter queue,
where an alarm picks it up. The alert itself is already marked failed with
the error in its trace by run_round.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fleetalert import repositories
from fleetalert.handlers.agent_loop_handler import run_round
from fleetalert.logging_config import configure_logging
from fleetalert.workflow import start_confirmation_wait

configure_logging()
_logger = logging.getLogger(__name__)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    failures = []
    for record in event.get("Records", []):
        try:
            process(json.loads(record["body"]))
        except Exception:
            _logger.exception("investigation message failed: %s", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def process(message: dict[str, Any]) -> dict[str, Any]:
    result = run_round(message)
    if result.get("outcome") == "awaiting_confirmation":
        alert = repositories.get_alert(message["alert_id"]) or {}
        start_confirmation_wait(
            message["alert_id"],
            str(message.get("entry_point") or "web"),
            str(alert.get("current_trace_id") or "unknown"),
        )
    return result
