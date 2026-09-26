"""Shared guardrail constants and the exception used to enforce them.

See docs/decisions/ADR-0002-fixed-action-whitelist.md for the whitelist
itself (fleetalert.whitelist) -- this module holds the other numeric/
exception-shaped guardrails referenced from fleetalert.agent.loop.
"""

MAX_LOOP_ITERATIONS = 6

# How many times a rejected proposal triggers another RAG-backed
# re-investigation before giving up and routing to support. 1 round means
# up to 2 total proposed fixes (the original, plus one alternative) -- for
# this demo, a single reject-and-retry is enough to show the loop without
# letting a visitor bounce a fix back and forth indefinitely.
MAX_REJECTION_ROUNDS = 1


class GuardrailViolation(Exception):
    """Raised when code attempts to cross a guardrail boundary.

    Always a programming/protocol error, never a normal outcome -- e.g. an
    execute_fix call with a stale or forged confirmation token. Contrast
    with "routed_to_support", which is the expected, non-exceptional outcome
    when the *agent* proposes something outside the whitelist.
    """
