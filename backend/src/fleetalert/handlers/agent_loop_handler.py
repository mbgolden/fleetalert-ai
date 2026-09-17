"""Lambda entrypoint for the Step Functions 'RunInvestigation' task."""

from __future__ import annotations

import os
from typing import Any

import anthropic
import boto3

from fleetalert.agent.loop import run_investigation

_secret_cache: dict[str, str] = {}


def _get_anthropic_api_key() -> str:
    """Cached across warm Lambda invocations, fetched fresh on cold start.

    The key itself never lives in a Lambda environment variable -- only the
    secret's ARN does. See docs/decisions/ for why (never hardcode/plainly
    expose the LLM API key).
    """
    secret_arn = os.environ["ANTHROPIC_SECRET_ARN"]
    if secret_arn not in _secret_cache:
        client = boto3.client("secretsmanager")
        _secret_cache[secret_arn] = client.get_secret_value(SecretId=secret_arn)["SecretString"]
    return _secret_cache[secret_arn]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    client = anthropic.Anthropic(api_key=_get_anthropic_api_key())
    return run_investigation(event["alert_id"], client)
