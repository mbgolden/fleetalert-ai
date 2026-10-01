"""Lambda entrypoint for load tests (ADR-0023), invoked by the Load test
GitHub workflow: {"action": "run" | "report" | "cleanup", "label": ...}."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import boto3

from fleetalert import loadtest
from fleetalert.logging_config import configure_logging
from fleetalert.workflow import enqueue_investigation, start_investigation

configure_logging()


def _direct(alert_id: str, entry_point: str, extra: dict[str, Any]) -> None:
    """Straight into Step Functions, as before the queue existed. Kept so a
    run can show what unqueued overload does."""
    start_investigation(alert_id, entry_point, extra)


def _queued(alert_id: str, entry_point: str, extra: dict[str, Any]) -> None:
    enqueue_investigation(alert_id, entry_point, extra)


def _cloudwatch(first: str, last: str) -> dict[str, float]:
    """What AWS saw during the run: Lambda throttles and peak concurrency
    for the round-running functions, API throttles (is the public site
    being starved?), queue backlog, dead letters, failed executions."""
    cw = boto3.client("cloudwatch")
    start, end = datetime.fromisoformat(first), datetime.fromisoformat(last)

    def stat(namespace: str, metric: str, dims: list[dict[str, str]], statistic: str) -> float:
        points = cw.get_metric_statistics(
            Namespace=namespace, MetricName=metric, Dimensions=dims,
            StartTime=start, EndTime=end, Period=60, Statistics=[statistic],
        )["Datapoints"]
        values = [p[statistic] for p in points]
        if not values:
            return 0.0
        return float(max(values) if statistic == "Maximum" else sum(values))

    def fn(env: str) -> list[dict[str, str]]:
        return [{"Name": "FunctionName", "Value": os.environ[env]}]

    def queue(env: str) -> list[dict[str, str]]:
        return [{"Name": "QueueName", "Value": os.environ[env]}]

    sfn = [{"Name": "StateMachineArn", "Value": os.environ["STATE_MACHINE_ARN"]}]
    return {
        "worker_throttles": stat("AWS/Lambda", "Throttles", fn("WORKER_FUNCTION_NAME"), "Sum"),
        "worker_peak_concurrency": stat("AWS/Lambda", "ConcurrentExecutions", fn("WORKER_FUNCTION_NAME"), "Maximum"),
        "agent_loop_throttles": stat("AWS/Lambda", "Throttles", fn("AGENT_LOOP_FUNCTION_NAME"), "Sum"),
        "agent_loop_peak_concurrency": stat(
            "AWS/Lambda", "ConcurrentExecutions", fn("AGENT_LOOP_FUNCTION_NAME"), "Maximum"
        ),
        "api_throttles": stat("AWS/Lambda", "Throttles", fn("API_FUNCTION_NAME"), "Sum"),
        "queue_oldest_message_s": stat(
            "AWS/SQS", "ApproximateAgeOfOldestMessage", queue("INVESTIGATION_QUEUE_NAME"), "Maximum"
        ),
        "queue_peak_depth": stat(
            "AWS/SQS", "ApproximateNumberOfMessagesVisible", queue("INVESTIGATION_QUEUE_NAME"), "Maximum"
        ),
        "dead_letters": stat(
            "AWS/SQS", "ApproximateNumberOfMessagesVisible", queue("INVESTIGATION_DLQ_NAME"), "Maximum"
        ),
        "sfn_executions_failed": stat("AWS/States", "ExecutionsFailed", sfn, "Sum"),
    }


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    action = event["action"]
    if action == "cleanup_all":
        return loadtest.cleanup(None)
    label = str(event["label"])
    if action == "run":
        return loadtest.run(
            label,
            rate_per_hour=int(event["rate_per_hour"]),
            minutes=float(event["minutes"]),
            model_latency_ms=int(event.get("model_latency_ms") or 0),
            start=_direct if event.get("path") == "direct" else _queued,
        )
    if action == "report":
        return loadtest.report(label, cloudwatch=_cloudwatch)
    if action == "cleanup":
        return loadtest.cleanup(label)
    raise ValueError(f"Unknown action: {action}")
