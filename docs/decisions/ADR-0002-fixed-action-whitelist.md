# ADR-0002: Fixed action whitelist instead of agent-generated action types

## Status
Accepted

## Context
`propose_fix` lets the agent name a fix type and describe it. That fix type
could either be validated against a fixed, hardcoded list, or left open —
letting the model invent new action identifiers as it encounters new
symptoms, with the system trusting whatever it emits.

## Decision
Fix types are restricted to a small, hardcoded whitelist
(`restart_sensor`, `schedule_service_visit`, `send_diagnostic_reset` — see
`backend/src/fleetalert/whitelist.py`). Anything else the agent proposes is
automatically routed to human support and never reaches `execute_fix`. The
whitelist is checked twice: once when the fix is proposed, again immediately
before execution (defense in depth against the value being tampered with or
the code path changing between those two points).

## Decision drivers
- This is a public demo with a real (if scoped) blast radius — an LLM output
  should never be the sole gate on what code executes.
- A whitelist makes the safe/unsafe boundary a static, reviewable list
  instead of an emergent property of prompting. It's the difference between
  "we constrained what's possible" and "we asked it nicely not to."
- It's honest about what the agent actually contributes: diagnosis and
  triage, not unconstrained remediation authority.

## Consequences
- The agent cannot resolve a novel problem type without a code change first
  (add the fix type to the whitelist, plus whatever `execute_fix` logic
  handles it). That's the intended limitation, not a gap to close later.
- Every whitelist miss should route cleanly to "human support," which itself
  needs to be a real, testable, logged outcome — not a silent drop.
