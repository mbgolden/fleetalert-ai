"""Tool schemas (for Claude's tool-use API) and the server-side dispatcher.

The model only ever gets a machine/symptom description back from these
tools -- never raw access to arbitrary machine_ids or timestamps. Each
tool's scope is implicitly fixed to *this* alert's machine, so the model
can't wander off and query telemetry for a different machine than the one
it was asked to investigate; that's decided by the calling code
(fleetalert.agent.loop), not by trusting whatever the model passes in.

propose_fix deliberately does not check the whitelist here -- it only
records that a proposal was received. The whitelist gate is enforced by
the caller (fleetalert.agent.loop._finalize_proposed_fix), which is guardrail
check #1 of 2 described in docs/decisions/ADR-0002-fixed-action-whitelist.md;
execute_fix (fleetalert.agent.loop.execute_fix) re-checks it as #2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fleetalert import repositories
from fleetalert.whitelist import ALLOWED_FIX_TYPES

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_telemetry_snapshot",
        "description": (
            "Get telemetry readings for this alert's machine, in a window of "
            "minutes before and after the alert was created."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "window_minutes": {
                    "type": "integer",
                    "description": "Minutes before and after the alert's creation time to include.",
                    "minimum": 1,
                    "maximum": 180,
                }
            },
            "required": ["window_minutes"],
        },
    },
    {
        "name": "search_knowledge_base",
        "description": (
            "Search the knowledge base for entries matching this alert's machine "
            "type and a symptom description. May return multiple entries that "
            "disagree with each other -- that is expected, not a bug."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symptom_description": {
                    "type": "string",
                    "description": "Short description of the observed symptom.",
                }
            },
            "required": ["symptom_description"],
        },
    },
    {
        "name": "get_service_history",
        "description": "Get past service events for this alert's machine.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "propose_fix",
        "description": (
            "Finalize a proposed fix for this alert. This does not execute "
            "anything -- a human must confirm it first. fix_id must be one of: "
            f"{', '.join(sorted(ALLOWED_FIX_TYPES))}. Any other fix_id will be "
            "automatically routed to human support instead of executed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fix_id": {
                    "type": "string",
                    "description": "The fix type to apply, e.g. 'restart_sensor'.",
                },
                "description": {
                    "type": "string",
                    "description": "Root cause summary and rationale for this fix.",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Confidence in this fix, from 0 to 1.",
                },
            },
            "required": ["fix_id", "description", "confidence"],
        },
    },
]


def execute_tool(
    name: str, tool_input: dict[str, Any], *, alert: dict[str, Any], machine: dict[str, Any]
) -> dict[str, Any]:
    if name == "get_telemetry_snapshot":
        window = timedelta(minutes=tool_input["window_minutes"])
        created_at = datetime.fromisoformat(alert["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        start = (created_at - window).isoformat()
        end = (created_at + window).isoformat()
        readings = repositories.get_telemetry_snapshot(alert["machine_id"], start, end)
        return {"readings": readings}

    if name == "search_knowledge_base":
        matches = repositories.search_knowledge_base(
            machine["machine_type"], tool_input["symptom_description"]
        )
        return {"matches": matches}

    if name == "get_service_history":
        history = repositories.get_service_history(alert["machine_id"])
        return {"service_history": history}

    if name == "propose_fix":
        return {"received": True, "fix_id": tool_input["fix_id"]}

    raise ValueError(f"Unknown tool: {name}")
