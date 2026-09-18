"""Structured logging, configured once per Lambda cold start.

JSON output so CloudWatch Logs Insights can filter/aggregate by field --
most usefully `alert_id`, since that's what ties one log line to one
investigation across all four Lambdas and the Step Functions execution
wrapping them. This is deliberately separate from the DynamoDB AuditLog
table: the audit log is the business-level trace (what a demo visitor sees
in the UI), this is the technical/ops trace (what an engineer watching
CloudWatch during a demo, or debugging afterward, needs) -- same "exact
path taken" story, two different audiences.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fleetalert import config


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        alert_id = getattr(record, "alert_id", None)
        if alert_id is not None:
            payload["alert_id"] = alert_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    """Idempotent -- safe to call at the top of every handler module.

    The Lambda runtime pre-attaches its own handler to the root logger
    before user code runs, so this reformats whatever's already there
    rather than assuming a clean slate (which is what `logging.basicConfig`
    assumes, and why it's not used here).
    """
    root = logging.getLogger()
    root.setLevel(config.log_level())
    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(_JsonFormatter())
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        root.addHandler(handler)


def alert_logger(name: str, alert_id: str) -> logging.LoggerAdapter[logging.Logger]:
    """A logger that stamps every line with alert_id automatically."""
    return logging.LoggerAdapter(logging.getLogger(name), {"alert_id": alert_id})
