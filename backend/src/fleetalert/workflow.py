"""Starting an investigation: the one call every entry point makes.

Web (api_handler's /investigate route) and email (email_intake) both start
the same Step Functions execution, differing only in `entry_point`, so the
same loop, Capabilities Engine and human-confirmation wait run either way.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

import boto3

from fleetalert import config


@cache
def _stepfunctions() -> Any:
    # Reused per container, like the DynamoDB resource (see fleetalert.db).
    return boto3.client("stepfunctions")


def start_investigation(alert_id: str, entry_point: str, extra: dict[str, Any] | None = None) -> None:
    state_machine_arn = config.require(config.state_machine_arn(), "STATE_MACHINE_ARN")
    _stepfunctions().start_execution(
        stateMachineArn=state_machine_arn,
        input=json.dumps({"alert_id": alert_id, "entry_point": entry_point, **(extra or {})}),
    )
