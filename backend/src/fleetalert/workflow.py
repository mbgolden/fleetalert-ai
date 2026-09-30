"""Starting an investigation: the one call every entry point makes.

Web (api_handler's /investigate route) and email (email_intake) both start
the same Step Functions execution, differing only in `entry_point`, so the
same loop, Capabilities Engine and human-confirmation wait run either way.
"""

from __future__ import annotations

import json

import boto3

from fleetalert import config


def start_investigation(alert_id: str, entry_point: str) -> None:
    state_machine_arn = config.require(config.state_machine_arn(), "STATE_MACHINE_ARN")
    boto3.client("stepfunctions").start_execution(
        stateMachineArn=state_machine_arn,
        input=json.dumps({"alert_id": alert_id, "entry_point": entry_point}),
    )
