"""Lambda entrypoint for the Step Functions 'ConfirmationTimedOut' state:
nobody confirmed or rejected within WaitForConfirmation's timeout."""

from __future__ import annotations

from typing import Any

from fleetalert.agent.loop import expire_confirmation
from fleetalert.logging_config import alert_logger, configure_logging

configure_logging()


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    alert_id = event["alert_id"]
    result = expire_confirmation(alert_id)
    alert_logger(__name__, alert_id).info("confirmation timeout handled: %s", result.get("outcome"))
    return result
