"""Lambda entrypoint for the scheduled email entry point (EventBridge,
every 4 hours). The demo's "Simulate inbound email" button runs the same
fleetalert.email_intake code through the API instead."""

from __future__ import annotations

import logging
from typing import Any

from fleetalert.email_intake import deliver_inbound_email
from fleetalert.logging_config import configure_logging
from fleetalert.workflow import start_investigation

configure_logging()
_logger = logging.getLogger(__name__)


def handler(_event: dict[str, Any], _context: Any) -> dict[str, Any]:
    result = deliver_inbound_email(start_investigation, trigger="schedule")
    _logger.info("scheduled inbound email: %s", result)
    return result
