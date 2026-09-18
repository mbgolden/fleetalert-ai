"""Lambda entrypoint for the Step Functions 'ExecuteFix' task.

Only reachable after WaitForConfirmation's callback resolves -- see
fleetalert.agent.loop.execute_fix for the guardrail checks (status,
confirmation_token match, whitelist re-check) that actually gate this.
"""

from __future__ import annotations

from typing import Any

from fleetalert import repositories
from fleetalert.agent.loop import execute_fix


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    alert_id = event["alert_id"]
    try:
        return execute_fix(alert_id, event["fix_id"], event["confirmation_token"])
    except Exception:
        # See agent_loop_handler._mark_failed -- same best-effort pattern,
        # for the same Retry/Catch structure on this task in the state
        # machine.
        _mark_failed(alert_id)
        raise


def _mark_failed(alert_id: str) -> None:
    try:
        repositories.update_alert(alert_id, status="failed")
        repositories.append_audit_log(alert_id, actor="system", action="execution_failed", details={})
    except Exception:  # noqa: BLE001, S110 -- best-effort; must never mask the real error  # nosec B110
        pass
