"""How an investigation gets started. See docs/decisions/ADR-0024.

Two paths into the same loop, guardrails and human-confirmation wait:

- **Direct** (`start_investigation`): a visitor clicking Investigate
  starts the Step Functions execution straight away. Human-paced, so it
  never arrives in bulk.
- **Queued** (`enqueue_investigation`): machine-generated alerts (inbound
  email, the telemetry detector, load tests) go onto an SQS queue. A worker
  Lambda takes them off with a fixed concurrency cap, runs the round, and
  only then starts a Step Functions execution, at the confirmation wait,
  if a human needs to decide (`start_confirmation_wait`). Under overload
  alerts wait in the queue instead of being throttled, retried and lost.
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


@cache
def _sqs() -> Any:
    return boto3.client("sqs")


def start_investigation(alert_id: str, entry_point: str, extra: dict[str, Any] | None = None) -> None:
    state_machine_arn = config.require(config.state_machine_arn(), "STATE_MACHINE_ARN")
    _stepfunctions().start_execution(
        stateMachineArn=state_machine_arn,
        input=json.dumps({"alert_id": alert_id, "entry_point": entry_point, **(extra or {})}),
    )


def enqueue_investigation(alert_id: str, entry_point: str, extra: dict[str, Any] | None = None) -> None:
    queue_url = config.require(config.investigation_queue_url(), "INVESTIGATION_QUEUE_URL")
    _sqs().send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({"alert_id": alert_id, "entry_point": entry_point, **(extra or {})}),
    )


def start_confirmation_wait(alert_id: str, entry_point: str, trace_id: str) -> None:
    """Start the state machine at the human-confirmation wait, for a round
    the queue worker already ran.

    The execution is named after the round, so a duplicate (SQS delivers at
    least once) is refused by Step Functions instead of creating a second
    wait for the same proposal.
    """
    state_machine_arn = config.require(config.state_machine_arn(), "STATE_MACHINE_ARN")
    client = _stepfunctions()
    try:
        client.start_execution(
            stateMachineArn=state_machine_arn,
            name=f"{alert_id}-{trace_id}"[:80],
            input=json.dumps(
                {
                    "alert_id": alert_id,
                    "entry_point": entry_point,
                    "investigation": {"outcome": "awaiting_confirmation"},
                }
            ),
        )
    except client.exceptions.ExecutionAlreadyExists:
        pass
