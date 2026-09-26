"""Lambda entrypoint for the demo's API Gateway routes (HTTP API, payload
format 2.0 -- routeKey is "METHOD /path", path params come pre-parsed).

One Lambda for the whole API surface, not one per route: these are all
thin, low-traffic wrappers over fleetalert.repositories and
fleetalert.agent.loop sharing the same dependencies -- splitting further
would multiply IAM/Terraform boilerplate without a real isolation benefit
at this project's scale.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3

from fleetalert import config, repositories
from fleetalert.agent.guardrails import GuardrailViolation
from fleetalert.agent.loop import confirm_fix, reject_fix
from fleetalert.logging_config import alert_logger, configure_logging
from fleetalert.seed_data import reseed_demo_data

configure_logging()
_logger = logging.getLogger(__name__)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    route_key = event["routeKey"]
    path_params = event.get("pathParameters") or {}
    body = json.loads(event["body"]) if event.get("body") else {}
    _logger.info("route hit: %s", route_key)

    try:
        if route_key == "GET /demo/alerts":
            return _json(200, {"alerts": _list_alerts_with_machine_info()})

        if route_key == "POST /demo/alerts/{alert_id}/investigate":
            return _start_investigation(path_params["alert_id"])

        if route_key == "GET /demo/alerts/{alert_id}/status":
            return _get_status(path_params["alert_id"])

        if route_key == "POST /demo/alerts/{alert_id}/confirm":
            return _confirm(path_params["alert_id"], body)

        if route_key == "POST /demo/alerts/{alert_id}/reject":
            return _reject(path_params["alert_id"], body)

        if route_key == "GET /demo/alerts/{alert_id}/audit":
            return _json(200, {"audit_trail": repositories.get_audit_trail(path_params["alert_id"])})

        if route_key == "POST /demo/reset":
            return _reset_demo_data()
    except GuardrailViolation as exc:
        _logger.warning("route %s rejected by guardrail: %s", route_key, exc)
        return _json(403, {"error": str(exc)})
    except ValueError as exc:
        _logger.info("route %s: not found: %s", route_key, exc)
        return _json(404, {"error": str(exc)})

    _logger.warning("no such route: %s", route_key)
    return _json(404, {"error": f"No such route: {route_key}"})


def _list_alerts_with_machine_info() -> list[dict[str, Any]]:
    alerts = repositories.list_alerts()
    for alert in alerts:
        machine = repositories.get_machine(alert["machine_id"])
        if machine is not None:
            alert["machine_name"] = machine.get("name")
            alert["machine_type"] = machine.get("machine_type")
    return alerts


def _start_investigation(alert_id: str) -> dict[str, Any]:
    log = alert_logger(__name__, alert_id)
    state_machine_arn = config.require(config.state_machine_arn(), "STATE_MACHINE_ARN")
    boto3.client("stepfunctions").start_execution(
        stateMachineArn=state_machine_arn,
        input=json.dumps({"alert_id": alert_id}),
    )
    log.info("investigation triggered via API")
    return _json(202, {"alert_id": alert_id, "status": "investigation_started"})


def _get_status(alert_id: str) -> dict[str, Any]:
    alert = repositories.get_alert(alert_id)
    if alert is None:
        return _json(404, {"error": f"No such alert: {alert_id}"})
    return _json(
        200,
        {
            "alert_id": alert_id,
            "status": alert.get("status"),
            "proposed_fix": alert.get("proposed_fix"),
            "confidence": alert.get("confidence"),
            "root_cause_summary": alert.get("root_cause_summary"),
            "confirmation_token": alert.get("confirmation_token"),
        },
    )


def _confirm(alert_id: str, body: dict[str, Any]) -> dict[str, Any]:
    log = alert_logger(__name__, alert_id)
    result = confirm_fix(alert_id, body.get("confirmation_token", ""))

    task_token = result.get("step_functions_task_token")
    if task_token:
        log.info("resuming Step Functions via SendTaskSuccess")
        boto3.client("stepfunctions").send_task_success(
            taskToken=task_token,
            output=json.dumps(
                {
                    "alert_id": alert_id,
                    "fix_id": result["fix_id"],
                    "confirmation_token": result["confirmation_token"],
                }
            ),
        )
    else:
        log.warning("confirmed but no step_functions_task_token on the alert -- nothing to resume")
    return _json(200, {"alert_id": alert_id, "outcome": "confirmed"})


def _reject(alert_id: str, body: dict[str, Any]) -> dict[str, Any]:
    log = alert_logger(__name__, alert_id)
    alert = repositories.get_alert(alert_id)
    if alert is None:
        return _json(404, {"error": f"No such alert: {alert_id}"})
    task_token = alert.get("step_functions_task_token")

    result = reject_fix(alert_id, reason=body.get("reason"))

    if task_token:
        # RetryWithNewFix loops the state machine back to RunInvestigation
        # (see infra/modules/step_functions); RoutedToSupport lands it on
        # the existing terminal RoutedToSupport success state. Either way
        # this is a normal, expected outcome of reject_fix -- "Rejected" is
        # reserved for a WaitForConfirmation failure we didn't cause.
        error_name = "RetryWithNewFix" if result["outcome"] == "investigating" else "RoutedToSupport"
        log.info("failing Step Functions wait via SendTaskFailure (%s)", error_name)
        boto3.client("stepfunctions").send_task_failure(
            taskToken=task_token,
            error=error_name,
            cause=body.get("reason") or "Rejected by visitor",
        )
    return _json(200, result)


def _reset_demo_data() -> dict[str, Any]:
    """Restores the fixed demo scenarios to their default state.

    Just data cleanup, not an agent action -- doesn't touch Step Functions
    or Claude at all, so there's no in-flight execution to cancel and
    nothing for the fixed action whitelist to gate. A concurrently-running
    investigation on a reset alert can still race this (put_item, not a
    conditional write), same as the existing seed script always could --
    acceptable for a public demo reset button, not worth the extra
    complexity to guard against here.
    """
    _logger.info("resetting demo data to defaults")
    reseed_demo_data()
    return _json(200, {"outcome": "reset"})


def _json(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, default=str),
    }
