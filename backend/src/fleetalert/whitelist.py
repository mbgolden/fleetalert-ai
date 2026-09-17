"""Fixed set of fix types the agent is allowed to execute.

See docs/decisions/ADR-0002-fixed-action-whitelist.md for why this is a
hardcoded list rather than something the agent can extend.
"""

ALLOWED_FIX_TYPES = frozenset(
    {
        "restart_sensor",
        "schedule_service_visit",
        "send_diagnostic_reset",
    }
)


def is_whitelisted(fix_type: str) -> bool:
    return fix_type in ALLOWED_FIX_TYPES
