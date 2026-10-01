"""Lambda entrypoint for the scheduled telemetry detector (EventBridge,
every 4 hours). The demo's "Run telemetry detector" button runs the same
fleetalert.autonomous code through the API instead."""

from __future__ import annotations

import logging
from typing import Any

from fleetalert.autonomous import run_detector
from fleetalert.logging_config import configure_logging
from fleetalert.workflow import enqueue_investigation

configure_logging()
_logger = logging.getLogger(__name__)


def handler(_event: dict[str, Any], _context: Any) -> dict[str, Any]:
    result = run_detector(enqueue_investigation, trigger="schedule")
    _logger.info("scheduled detector run: %s", result)
    return result
