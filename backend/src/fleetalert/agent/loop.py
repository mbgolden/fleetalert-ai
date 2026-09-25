"""The investigation loop, plus the confirm/reject/execute-fix guardrails.

`run_investigation` is the "Agent Loop Lambda" from the architecture
diagram: observe/plan/act via Claude's structured tool calling
(fleetalert.agent.tools) until the model calls propose_fix or the loop
exhausts MAX_LOOP_ITERATIONS. It never executes anything itself -- it only
ever ends in "awaiting_confirmation" (whitelisted fix, human must confirm)
or "routed_to_support" (non-whitelisted fix, or no fix reached in time).

A human rejecting a proposed fix (reject_fix, below) re-triggers this same
function rather than ending the investigation: the alert's status goes back
to "investigating" and Step Functions loops back to RunInvestigation (see
infra/modules/step_functions), so the model gets another pass with the
rejected fix_id(s) named in its prompt and is expected to search the
knowledge base for a different one. Capped at MAX_REJECTION_ROUNDS rounds
(fleetalert.agent.guardrails) before reject_fix gives up and routes to
support itself, so this never loops unboundedly.

`execute_fix` is deliberately a separate function, not a tool the model
calls mid-loop: in the real deployment this only runs after Step Functions'
task-token callback fires from a human confirming in the UI, never as a
direct continuation of the model's own reasoning. See:
- docs/decisions/ADR-0001-step-functions-task-token-callback.md
- docs/decisions/ADR-0002-fixed-action-whitelist.md
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fleetalert import config, repositories
from fleetalert.agent.guardrails import (
    MAX_LOOP_ITERATIONS,
    MAX_REJECTION_ROUNDS,
    GuardrailViolation,
)
from fleetalert.agent.tools import TOOL_SCHEMAS, execute_tool
from fleetalert.logging_config import alert_logger
from fleetalert.repositories import ConcurrentUpdateError
from fleetalert.whitelist import is_whitelisted

_CONTINUE_NUDGE = (
    "Continue the investigation using the available tools, or call "
    "propose_fix once you have enough information."
)


def run_investigation(
    alert_id: str,
    client: Any,
    *,
    model: str | None = None,
    max_iterations: int = MAX_LOOP_ITERATIONS,
) -> dict[str, Any]:
    model = model or config.anthropic_model()
    alert = repositories.get_alert(alert_id)
    if alert is None:
        raise ValueError(f"No such alert: {alert_id}")
    machine = repositories.get_machine(alert["machine_id"])
    if machine is None:
        raise ValueError(f"No such machine: {alert['machine_id']}")

    log = alert_logger(__name__, alert_id)

    try:
        repositories.update_alert_if_current(
            alert_id, expected_status=["open", "investigating"], status="investigating"
        )
    except ConcurrentUpdateError:
        # A duplicate trigger (double /investigate click, a retried Step
        # Functions execution) landed after this alert already moved past
        # open/investigating -- report the real outcome, don't re-run.
        log.info("duplicate investigation trigger ignored, reporting existing outcome")
        return _current_alert_outcome(alert_id)

    rejected_fixes = alert.get("rejected_fixes") or []
    log.info(
        "investigation started: alert_type=%s severity=%s machine_type=%s max_iterations=%d model=%s rejected_fixes=%d",
        alert["alert_type"],
        alert["severity"],
        machine["machine_type"],
        max_iterations,
        model,
        len(rejected_fixes),
    )
    repositories.append_audit_log(
        alert_id,
        actor="agent",
        action="investigation_started",
        details={"rejected_fixes": len(rejected_fixes)},
    )

    system_prompt = _build_system_prompt(machine)
    user_message = (
        f"Investigate alert {alert_id}: {alert['alert_type']} "
        f"(severity: {alert['severity']}) on machine {machine['name']} "
        f"({machine['machine_type']})."
    )
    if rejected_fixes:
        rejected_summary = "; ".join(
            f"{r['fix_id']!r} (reason: {r.get('reason') or 'not given'})" for r in rejected_fixes
        )
        user_message += (
            f" A human already rejected {len(rejected_fixes)} previously proposed "
            f"fix(es): {rejected_summary}. Do not propose any of those fix_ids again -- "
            "search the knowledge base for a different angle on this symptom and "
            "propose an alternative fix, or call propose_fix with a non-whitelisted "
            "fix_id (or stop calling tools) if nothing else plausible fits."
        )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    for iteration in range(1, max_iterations + 1):
        log.debug("loop iteration %d/%d: calling model", iteration, max_iterations)
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        if not tool_use_blocks:
            log.info("iteration %d/%d: model returned no tool call, nudging it to continue", iteration, max_iterations)
            messages.append({"role": "user", "content": _CONTINUE_NUDGE})
            continue

        tool_results = []
        propose_fix_input: dict[str, Any] | None = None
        for block in tool_use_blocks:
            log.info("iteration %d/%d: tool call -> %s", iteration, max_iterations, block.name)
            repositories.append_audit_log(
                alert_id, actor="agent", action=block.name, details={"input": block.input}
            )
            result = execute_tool(block.name, block.input, alert=alert, machine=machine)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)}
            )
            if block.name == "propose_fix":
                propose_fix_input = block.input

        messages.append({"role": "user", "content": tool_results})

        if propose_fix_input is not None:
            log.info("iteration %d/%d: propose_fix received -> fix_id=%s", iteration, max_iterations, propose_fix_input.get("fix_id"))
            return _finalize_proposed_fix(alert_id, propose_fix_input)

    log.warning("max_iterations (%d) exhausted without a proposed fix -- routing to support", max_iterations)
    return _route_to_support(alert_id, reason="max_iterations_exceeded")


def confirm_fix(alert_id: str, confirmation_token: str) -> dict[str, Any]:
    """Validates a human's confirm action; does not execute anything.

    Called by the (API Gateway) confirm handler before it calls
    SendTaskSuccess to resume the Step Functions wait. execute_fix runs
    later, asynchronously, once Step Functions resumes and reaches the
    ExecuteFix state -- a real time gap, unlike the loop's own steps, so
    "confirm" is logged here rather than bundled into execute_fix.
    """
    log = alert_logger(__name__, alert_id)
    alert = repositories.get_alert(alert_id)
    if alert is None:
        raise ValueError(f"No such alert: {alert_id}")
    if alert.get("status") != "awaiting_confirmation":
        log.warning("confirm rejected: status=%r is not awaiting_confirmation", alert.get("status"))
        raise GuardrailViolation(f"Alert {alert_id} is not awaiting confirmation")
    if alert.get("confirmation_token") != confirmation_token:
        log.warning("confirm rejected: confirmation_token mismatch")
        raise GuardrailViolation("Invalid confirmation token")

    fix_id = alert["proposed_fix"]
    log.info("confirmed by human -> fix_id=%s", fix_id)
    repositories.append_audit_log(alert_id, actor="human", action="confirm", details={"fix_id": fix_id})
    return {
        "alert_id": alert_id,
        "fix_id": fix_id,
        "confirmation_token": confirmation_token,
        "step_functions_task_token": alert.get("step_functions_task_token"),
    }


def execute_fix(alert_id: str, fix_id: str, confirmation_token: str) -> dict[str, Any]:
    """Only reachable with the token issued by _finalize_proposed_fix.

    Re-checks the whitelist as defense in depth -- should be unreachable
    given that gate, but this is the guardrail of last resort before
    anything actually runs.
    """
    log = alert_logger(__name__, alert_id)
    alert = repositories.get_alert(alert_id)
    if alert is None:
        raise ValueError(f"No such alert: {alert_id}")

    if alert.get("status") != "awaiting_confirmation":
        log.warning("execute_fix rejected: status=%r is not awaiting_confirmation", alert.get("status"))
        raise GuardrailViolation(f"Alert {alert_id} is not awaiting confirmation")
    if alert.get("confirmation_token") != confirmation_token:
        log.warning("execute_fix rejected: confirmation_token mismatch")
        raise GuardrailViolation("Invalid confirmation token")
    if alert.get("proposed_fix") != fix_id:
        log.warning("execute_fix rejected: fix_id=%s does not match proposed_fix=%s", fix_id, alert.get("proposed_fix"))
        raise GuardrailViolation("fix_id does not match the proposed fix")
    if not is_whitelisted(fix_id):
        log.error("execute_fix rejected: fix_id=%s is not whitelisted (should be unreachable)", fix_id)
        raise GuardrailViolation(f"Fix type {fix_id!r} is not whitelisted")

    try:
        repositories.update_alert_if_current(
            alert_id, expected_status="awaiting_confirmation", status="resolved"
        )
    except ConcurrentUpdateError as exc:
        log.warning("execute_fix lost a race: alert already resolved or moved on")
        raise GuardrailViolation(
            f"Alert {alert_id} was already resolved or moved on by another request"
        ) from exc

    log.info("fix executed -> fix_id=%s, status=resolved", fix_id)
    repositories.append_audit_log(alert_id, actor="agent", action="execute_fix", details={"fix_id": fix_id})
    return {"outcome": "resolved", "alert_id": alert_id, "fix_id": fix_id}


def reject_fix(alert_id: str, *, reason: str | None = None) -> dict[str, Any]:
    """Rejecting a proposal re-investigates for an alternative, up to a cap.

    Records the rejected fix_id and re-enters "investigating" so Step
    Functions loops back to RunInvestigation with that history in hand
    (see run_investigation) -- unless MAX_REJECTION_ROUNDS is already spent,
    in which case this routes straight to support instead of looping again.
    """
    log = alert_logger(__name__, alert_id)
    alert = repositories.get_alert(alert_id)
    if alert is None:
        raise ValueError(f"No such alert: {alert_id}")
    if alert.get("status") != "awaiting_confirmation":
        log.warning("reject rejected: status=%r is not awaiting_confirmation", alert.get("status"))
        raise GuardrailViolation(f"Alert {alert_id} is not awaiting confirmation")

    rejected_fixes = [
        *(alert.get("rejected_fixes") or []),
        {
            "fix_id": alert.get("proposed_fix"),
            "reason": reason,
            "rejected_at": datetime.now(UTC).isoformat(),
        },
    ]
    repositories.append_audit_log(
        alert_id, actor="human", action="reject",
        details={"reason": reason, "fix_id": alert.get("proposed_fix")},
    )

    if len(rejected_fixes) > MAX_REJECTION_ROUNDS:
        try:
            repositories.update_alert_if_current(
                alert_id,
                expected_status="awaiting_confirmation",
                status="routed_to_support",
                rejected_fixes=rejected_fixes,
                proposed_fix=None,
                confirmation_token=None,
            )
        except ConcurrentUpdateError as exc:
            log.warning("reject lost a race: alert already resolved or moved on")
            raise GuardrailViolation(
                f"Alert {alert_id} was already resolved or moved on by another request"
            ) from exc
        log.info("rejected by human, reason=%r -- rejection budget exhausted, routing to support", reason)
        repositories.append_audit_log(
            alert_id, actor="system", action="route_to_support",
            details={"reason": "rejection_budget_exhausted"},
        )
        return {"outcome": "routed_to_support", "alert_id": alert_id, "reason": "rejection_budget_exhausted"}

    try:
        repositories.update_alert_if_current(
            alert_id,
            expected_status="awaiting_confirmation",
            status="investigating",
            rejected_fixes=rejected_fixes,
            proposed_fix=None,
            confirmation_token=None,
        )
    except ConcurrentUpdateError as exc:
        log.warning("reject lost a race: alert already resolved or moved on")
        raise GuardrailViolation(
            f"Alert {alert_id} was already resolved or moved on by another request"
        ) from exc

    log.info(
        "rejected by human, reason=%r -- re-investigating (round %d/%d)",
        reason, len(rejected_fixes), MAX_REJECTION_ROUNDS,
    )
    return {"outcome": "investigating", "alert_id": alert_id, "rejected_fixes": rejected_fixes}


def _finalize_proposed_fix(alert_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
    log = alert_logger(__name__, alert_id)
    fix_id = proposal["fix_id"]

    alert = repositories.get_alert(alert_id)
    rejected_fix_ids = {r["fix_id"] for r in (alert.get("rejected_fixes") or [])} if alert else set()
    if fix_id in rejected_fix_ids:
        # The model didn't take the "don't repeat a rejected fix_id" prompt
        # instruction -- enforce it in code rather than trusting compliance.
        log.warning("proposed fix_id=%s was already rejected -- routing to support instead", fix_id)
        return _route_to_support(alert_id, reason="fix_already_rejected", fix_id=fix_id)

    if not is_whitelisted(fix_id):
        log.warning("proposed fix_id=%s is not whitelisted -- routing to support", fix_id)
        return _route_to_support(alert_id, reason="fix_not_whitelisted", fix_id=fix_id)

    log.info("proposed fix_id=%s is whitelisted -- awaiting human confirmation", fix_id)
    token = str(uuid.uuid4())
    try:
        repositories.update_alert_if_current(
            alert_id,
            expected_status="investigating",
            status="awaiting_confirmation",
            proposed_fix=fix_id,
            confidence=proposal.get("confidence"),
            root_cause_summary=proposal.get("description"),
            confirmation_token=token,
        )
    except ConcurrentUpdateError:
        # A retried invocation of this same investigation landed after an
        # earlier attempt already finished -- report what actually won
        # instead of clobbering it.
        return _current_alert_outcome(alert_id)

    repositories.append_audit_log(
        alert_id, actor="system", action="request_confirmation", details={"fix_id": fix_id}
    )
    return {
        "outcome": "awaiting_confirmation",
        "alert_id": alert_id,
        "fix_id": fix_id,
        "confirmation_token": token,
    }


def _route_to_support(alert_id: str, *, reason: str, fix_id: str | None = None) -> dict[str, Any]:
    log = alert_logger(__name__, alert_id)
    try:
        repositories.update_alert_if_current(
            alert_id, expected_status="investigating", status="routed_to_support"
        )
    except ConcurrentUpdateError:
        return _current_alert_outcome(alert_id)

    log.info("routed to support, reason=%s", reason)
    details: dict[str, Any] = {"reason": reason}
    if fix_id is not None:
        details["fix_id"] = fix_id
    repositories.append_audit_log(alert_id, actor="system", action="route_to_support", details=details)
    return {"outcome": "routed_to_support", "alert_id": alert_id, "reason": reason}


def _current_alert_outcome(alert_id: str) -> dict[str, Any]:
    """Reports whatever status already won a race, rather than raising.

    Only reachable after our own ConditionExpression has already proven the
    alert moved past "investigating" -- so status here is always one of the
    terminal-ish outcomes below, never "investigating" itself.
    """
    alert = repositories.get_alert(alert_id)
    status = alert.get("status") if alert else None
    if status == "awaiting_confirmation" and alert is not None:
        return {
            "outcome": "awaiting_confirmation",
            "alert_id": alert_id,
            "fix_id": alert.get("proposed_fix"),
            "confirmation_token": alert.get("confirmation_token"),
        }
    return {"outcome": status, "alert_id": alert_id}


def _build_system_prompt(machine: dict[str, Any]) -> str:
    return (
        "You are a fleet maintenance investigation assistant. You diagnose "
        "alerts on industrial machines by gathering evidence through tools, "
        "then propose a fix.\n\n"
        f"This machine is a {machine['machine_type']} ({machine['name']}).\n\n"
        "Use get_telemetry_snapshot, search_knowledge_base, and "
        "get_service_history to gather evidence before proposing anything. "
        "If knowledge base entries disagree with each other, say so "
        "explicitly in your proposed fix's description rather than silently "
        "picking one -- note the conflict and prefer the more cautious "
        "option. Call propose_fix exactly once, when ready to finalize a "
        "recommendation. You cannot execute any fix yourself; a human must "
        "confirm it first."
    )
