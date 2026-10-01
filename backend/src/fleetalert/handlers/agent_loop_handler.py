"""Lambda entrypoint for the Step Functions 'RunInvestigation' task."""

from __future__ import annotations

import json
from typing import Any

import anthropic
import boto3

from fleetalert import config, repositories
from fleetalert.agent.loop import run_investigation
from fleetalert.logging_config import alert_logger, configure_logging
from fleetalert.tracing import SpanKind, SpanStatus, Tracer

configure_logging()

_secret_cache: dict[str, str] = {}

# A JSON field name inside the secret, not a credential itself.
_SECRET_KEY_NAME = "anthropic-api-key"  # nosec B105


def _get_anthropic_api_key() -> str:
    """Cached across warm Lambda invocations, fetched fresh on cold start.

    The key itself never lives in a Lambda environment variable -- only the
    secret's ARN does. Stored as a Secrets Manager key/value pair (key
    "anthropic-api-key"), not plaintext, so SecretString is a JSON blob to
    unwrap, not the raw key itself.
    """
    secret_arn = config.require(config.anthropic_secret_arn(), "ANTHROPIC_SECRET_ARN")
    if secret_arn not in _secret_cache:
        client = boto3.client("secretsmanager")
        secret_string = client.get_secret_value(SecretId=secret_arn)["SecretString"]
        _secret_cache[secret_arn] = json.loads(secret_string)[_SECRET_KEY_NAME]
    return _secret_cache[secret_arn]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    alert_id = event["alert_id"]
    log = alert_logger(__name__, alert_id)
    log.info("RunInvestigation task invoked")
    try:
        client = anthropic.Anthropic(api_key=_get_anthropic_api_key())
        result = run_investigation(alert_id, client, entry_point=event.get("entry_point", "web"))
        log.info("RunInvestigation task complete: %s", result.get("outcome"))
        return result
    except Exception as exc:
        # Best-effort marker for whichever attempt turns out to be the
        # last one Step Functions makes (see infra/modules/step_functions
        # -- retried up to 6 times before landing on the Failed state).
        # Every earlier retry re-enters run_investigation, which resets
        # status back to "investigating" before this can matter; only the
        # final, un-retried failure leaves "failed" in place.
        log.exception("RunInvestigation task raised")
        _mark_failed(alert_id, exc)
        raise


def _mark_failed(alert_id: str, error: BaseException) -> None:
    try:
        repositories.update_alert(alert_id, status="failed")
        alert = repositories.get_alert(alert_id)
        if alert is not None:
            tracer = Tracer.continue_for(alert)
            tracer.record(
                name="execution_failed",
                kind=SpanKind.LIFECYCLE,
                actor="system",
                status=SpanStatus.FAILURE,
                parent_span_id=tracer.root_span_id,
                # The trace is what a visitor sees, so it should say what
                # broke, not just that something did.
                output={"error": f"{type(error).__name__}: {error}"[:500]},
            )
    except Exception:  # noqa: BLE001, S110 -- best-effort; must never mask the real error  # nosec B110
        pass
