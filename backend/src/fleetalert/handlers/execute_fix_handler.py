"""Lambda entrypoint for the Step Functions 'ExecuteFix' task.

Only reachable after WaitForConfirmation's callback resolves -- see
fleetalert.agent.loop.execute_fix for the guardrail checks (status,
confirmation_token match, whitelist re-check) that actually gate this.
"""

from __future__ import annotations

from typing import Any

from fleetalert import repositories
from fleetalert.agent.loop import execute_fix
from fleetalert.logging_config import alert_logger, configure_logging

configure_logging()


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    alert_id = event["alert_id"]
    log = alert_logger(__name__, alert_id)
    log.info("ExecuteFix task invoked, fix_id=%s", event.get("fix_id"))
    try:
        result = execute_fix(alert_id, event["fix_id"], event["confirmation_token"])
        log.info("ExecuteFix task complete: %s", result.get("outcome"))
        return result
    except Exception:
        # See agent_loop_handler._mark_failed -- same best-effort pattern,
        # for the same Retry/Catch structure on this task in the state
        # machine.
        log.exception("ExecuteFix task raised")
        _mark_failed(alert_id)
        raise


def _mark_failed(alert_id: str) -> None:
    try:
        repositories.update_alert(alert_id, status="failed")
        repositories.append_audit_log(alert_id, actor="system", action="execution_failed", details={})
    except Exception:  # noqa: BLE001, S110 -- best-effort; must never mask the real error  # nosec B110
        pass
