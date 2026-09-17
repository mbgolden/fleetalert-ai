"""Lambda entrypoint for the Step Functions 'ExecuteFix' task.

Only reachable after WaitForConfirmation's callback resolves -- see
fleetalert.agent.loop.execute_fix for the guardrail checks (status,
confirmation_token match, whitelist re-check) that actually gate this.
"""

from __future__ import annotations

from typing import Any

from fleetalert.agent.loop import execute_fix


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    return execute_fix(event["alert_id"], event["fix_id"], event["confirmation_token"])
