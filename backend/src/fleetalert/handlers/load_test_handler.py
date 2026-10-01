"""Lambda entrypoint for load tests (ADR-0023), invoked by the Load test
GitHub workflow: {"action": "run" | "report" | "cleanup", "label": ...}."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import boto3

from fleetalert import loadtest
from fleetalert.logging_config import configure_logging
from fleetalert.workflow import start_investigation

configure_logging()


def _start(alert_id: str, entry_point: str, extra: dict[str, Any]) -> None:
    start_investigation(alert_id, entry_point, extra)


def _cloudwatch(first: str, last: str) -> dict[str, float]:
    """Throttles, errors and peak concurrency for the agent-loop Lambda,
    and Step Functions failures, over the run's window."""
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

    fn = [{"Name": "FunctionName", "Value": os.environ["AGENT_LOOP_FUNCTION_NAME"]}]
    sfn = [{"Name": "StateMachineArn", "Value": os.environ["STATE_MACHINE_ARN"]}]
    return {
        "lambda_throttles": stat("AWS/Lambda", "Throttles", fn, "Sum"),
        "lambda_errors": stat("AWS/Lambda", "Errors", fn, "Sum"),
        "lambda_peak_concurrency": stat("AWS/Lambda", "ConcurrentExecutions", fn, "Maximum"),
        "sfn_executions_failed": stat("AWS/States", "ExecutionsFailed", sfn, "Sum"),
    }


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    action = event["action"]
    if action == "cleanup_all":
        return loadtest.cleanup(None)
    label = str(event["label"])
    if action == "run":
        return loadtest.run(
            label, rate_per_hour=int(event["rate_per_hour"]), minutes=float(event["minutes"]), start=_start
        )
    if action == "report":
        return loadtest.report(label, cloudwatch=_cloudwatch)
    if action == "cleanup":
        return loadtest.cleanup(label)
    raise ValueError(f"Unknown action: {action}")
