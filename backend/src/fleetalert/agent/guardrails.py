"""Shared guardrail constants and the exception used to enforce them.

See docs/decisions/ADR-0002-fixed-action-whitelist.md for the whitelist
itself (fleetalert.whitelist) -- this module holds the other numeric/
exception-shaped guardrails referenced from fleetalert.agent.loop.
"""

MAX_LOOP_ITERATIONS = 6


class GuardrailViolation(Exception):
    """Raised when code attempts to cross a guardrail boundary.

    Always a programming/protocol error, never a normal outcome -- e.g. an
    execute_fix call with a stale or forged confirmation token. Contrast
    with "routed_to_support", which is the expected, non-exceptional outcome
    when the *agent* proposes something outside the whitelist.
    """
