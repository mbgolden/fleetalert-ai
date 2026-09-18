"""Lambda entrypoint for the Step Functions 'RunInvestigation' task."""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic
import boto3

from fleetalert import repositories
from fleetalert.agent.loop import run_investigation

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
    secret_arn = os.environ["ANTHROPIC_SECRET_ARN"]
    if secret_arn not in _secret_cache:
        client = boto3.client("secretsmanager")
        secret_string = client.get_secret_value(SecretId=secret_arn)["SecretString"]
        _secret_cache[secret_arn] = json.loads(secret_string)[_SECRET_KEY_NAME]
    return _secret_cache[secret_arn]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    alert_id = event["alert_id"]
    try:
        client = anthropic.Anthropic(api_key=_get_anthropic_api_key())
        return run_investigation(alert_id, client)
    except Exception:
        # Best-effort marker for whichever attempt turns out to be the
        # last one Step Functions makes (see infra/modules/step_functions
        # -- retried up to 6 times before landing on the Failed state).
        # Every earlier retry re-enters run_investigation, which resets
        # status back to "investigating" before this can matter; only the
        # final, un-retried failure leaves "failed" in place.
        _mark_failed(alert_id)
        raise


def _mark_failed(alert_id: str) -> None:
    try:
        repositories.update_alert(alert_id, status="failed")
        repositories.append_audit_log(alert_id, actor="system", action="execution_failed", details={})
    except Exception:  # noqa: BLE001, S110 -- best-effort; must never mask the real error  # nosec B110
        pass
