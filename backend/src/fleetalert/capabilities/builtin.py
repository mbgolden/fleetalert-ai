"""The capabilities FleetAlert registers. Contracts: docs/capabilities/.

Machine scope always comes from the context (the alert being investigated),
never from model input -- the model can't point a read at a different
machine than the one it was asked about.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fleetalert import repositories
from fleetalert.agent.guardrails import GuardrailViolation
from fleetalert.capabilities.registry import Capability, CapabilityContext, SafetyTier
from fleetalert.repositories import ConcurrentUpdateError
from fleetalert.whitelist import ALLOWED_FIX_TYPES, is_whitelisted

OWNER = "FleetAlert agents platform (Michael Golden)"

# Field order is deliberate: the model writes tool input in schema order, so
# the short fields come before the long rationale. With description second,
# a response cut off at max_tokens lost confidence every time (first
# recorded eval run; see docs/decisions/ADR-0012).
_FIX_FIELDS: dict[str, Any] = {
    "fix_id": {
        "type": "string",
        "minLength": 1,
        "description": "The fix type to apply, e.g. 'restart_sensor'.",
    },
    "confidence": {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
        "description": "Confidence in this fix, from 0 to 1.",
    },
    "description": {
        "type": "string",
        "minLength": 1,
        "pattern": r"\S",
        "description": (
            "Root cause and rationale in 2-5 sentences (under 150 words): the "
            "telemetry values and KB entries that support this fix."
        ),
    },
}


def _telemetry(tool_input: dict[str, Any], ctx: CapabilityContext) -> dict[str, Any]:
    window = timedelta(minutes=tool_input["window_minutes"])
    created_at = datetime.fromisoformat(ctx.alert["created_at"])
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    readings = repositories.get_telemetry_snapshot(
        ctx.alert["machine_id"], (created_at - window).isoformat(), (created_at + window).isoformat()
    )
    return {"readings": readings}


def _knowledge_base(tool_input: dict[str, Any], ctx: CapabilityContext) -> dict[str, Any]:
    if ctx.machine is None:
        raise ValueError("search_knowledge_base needs the alert's machine in context")
    return {
        "matches": repositories.search_knowledge_base(
            ctx.machine["machine_type"], tool_input["symptom_description"]
        )
    }


def _service_history(_tool_input: dict[str, Any], ctx: CapabilityContext) -> dict[str, Any]:
    return {"service_history": repositories.get_service_history(ctx.alert["machine_id"])}


def _propose_fix(tool_input: dict[str, Any], _ctx: CapabilityContext) -> dict[str, Any]:
    # Recording only. Whether the proposal can go further (whitelist,
    # already-rejected) is decided in code by the loop, not here.
    return {"received": True, "fix_id": tool_input["fix_id"]}


def _request_confirmation(tool_input: dict[str, Any], ctx: CapabilityContext) -> dict[str, Any]:
    alert_id = ctx.alert["alert_id"]
    token = str(uuid.uuid4())
    try:
        repositories.update_alert_if_current(
            alert_id,
            expected_status="investigating",
            status="awaiting_confirmation",
            proposed_fix=tool_input["fix_id"],
            confidence=tool_input["confidence"],
            root_cause_summary=tool_input["description"],
            confirmation_token=token,
        )
    except ConcurrentUpdateError:
        # A retried invocation landed after an earlier attempt already
        # finished; the caller reports what won instead of clobbering it.
        return {"status": "superseded", "fix_id": tool_input["fix_id"]}
    return {"status": "awaiting_confirmation", "fix_id": tool_input["fix_id"], "confirmation_token": token}


def _execute_fix(tool_input: dict[str, Any], ctx: CapabilityContext) -> dict[str, Any]:
    """The guardrail of last resort before anything runs."""
    alert_id = ctx.alert["alert_id"]
    alert = repositories.get_alert(alert_id)
    if alert is None:
        raise ValueError(f"No such alert: {alert_id}")
    fix_id = tool_input["fix_id"]
    if alert.get("status") != "awaiting_confirmation":
        raise GuardrailViolation(f"Alert {alert_id} is not awaiting confirmation")
    if alert.get("confirmation_token") != tool_input["confirmation_token"]:
        raise GuardrailViolation("Invalid confirmation token")
    if alert.get("proposed_fix") != fix_id:
        raise GuardrailViolation("fix_id does not match the proposed fix")
    if not is_whitelisted(fix_id):
        raise GuardrailViolation(f"Fix type {fix_id!r} is not whitelisted")
    try:
        repositories.update_alert_if_current(alert_id, expected_status="awaiting_confirmation", status="resolved")
    except ConcurrentUpdateError as exc:
        raise GuardrailViolation(
            f"Alert {alert_id} was already resolved or moved on by another request"
        ) from exc
    return {"status": "resolved", "fix_id": fix_id}


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


BUILTIN_CAPABILITIES: list[Capability] = [
    Capability(
        name="get_telemetry_snapshot",
        description=(
            "Get telemetry readings for this alert's machine, in a window of "
            "minutes before and after the alert was created."
        ),
        input_schema=_object(
            {
                "window_minutes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 180,
                    "description": "Minutes before and after the alert's creation time to include.",
                }
            },
            ["window_minutes"],
        ),
        output_schema=_object(
            {
                "readings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["machine_id", "timestamp", "signal_readings"],
                        "properties": {"signal_readings": {"type": "object"}},
                    },
                }
            },
            ["readings"],
        ),
        safety_tier=SafetyTier.READ_ONLY,
        idempotent=True,
        owner=OWNER,
        handler=_telemetry,
        agent_callable=True,
    ),
    Capability(
        name="search_knowledge_base",
        description=(
            "Search the knowledge base for entries matching this alert's machine "
            "type and a symptom description. May return multiple entries that "
            "disagree with each other -- that is expected, not a bug."
        ),
        input_schema=_object(
            {
                "symptom_description": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Short description of the observed symptom.",
                }
            },
            ["symptom_description"],
        ),
        output_schema=_object(
            {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["kb_id", "issue_pattern", "description", "known_fix"],
                    },
                }
            },
            ["matches"],
        ),
        safety_tier=SafetyTier.READ_ONLY,
        idempotent=True,
        owner=OWNER,
        handler=_knowledge_base,
        agent_callable=True,
    ),
    Capability(
        name="get_service_history",
        description="Get past service events for this alert's machine.",
        input_schema=_object({}, []),
        output_schema=_object({"service_history": {"type": "array"}}, ["service_history"]),
        safety_tier=SafetyTier.READ_ONLY,
        idempotent=True,
        owner=OWNER,
        handler=_service_history,
        agent_callable=True,
    ),
    Capability(
        name="propose_fix",
        description=(
            "Finalize a proposed fix for this alert. This does not execute "
            "anything -- a human must confirm it first. fix_id must be one of: "
            f"{', '.join(sorted(ALLOWED_FIX_TYPES))}. Any other fix_id will be "
            "automatically routed to human support instead of executed."
        ),
        input_schema=_object(_FIX_FIELDS, ["fix_id", "confidence", "description"]),
        output_schema=_object(
            {"received": {"const": True}, "fix_id": {"type": "string"}}, ["received", "fix_id"]
        ),
        safety_tier=SafetyTier.PROPOSES_ACTION,
        idempotent=True,
        owner=OWNER,
        handler=_propose_fix,
        agent_callable=True,
    ),
    Capability(
        name="request_confirmation",
        description=(
            "Move the alert to awaiting_confirmation and issue the confirmation "
            "token the human's confirm must present. Invoked by the loop, never "
            "by the model."
        ),
        input_schema=_object(_FIX_FIELDS, ["fix_id", "confidence", "description"]),
        output_schema={
            "type": "object",
            "properties": {
                "status": {"enum": ["awaiting_confirmation", "superseded"]},
                "fix_id": {"type": "string"},
                "confirmation_token": {"type": "string"},
            },
            "required": ["status", "fix_id"],
            "additionalProperties": False,
        },
        safety_tier=SafetyTier.PROPOSES_ACTION,
        idempotent=False,
        owner=OWNER,
        handler=_request_confirmation,
    ),
    Capability(
        name="execute_fix",
        description=(
            "Run a confirmed, whitelisted fix. Only callable with the confirmation "
            "token from the Step Functions wait state; re-checks the whitelist."
        ),
        input_schema=_object(
            {
                "fix_id": {"type": "string", "minLength": 1},
                "confirmation_token": {"type": "string", "minLength": 1},
            },
            ["fix_id", "confirmation_token"],
        ),
        output_schema=_object(
            {"status": {"const": "resolved"}, "fix_id": {"type": "string"}}, ["status", "fix_id"]
        ),
        safety_tier=SafetyTier.EXECUTES_ACTION,
        idempotent=False,
        owner=OWNER,
        handler=_execute_fix,
    ),
]
