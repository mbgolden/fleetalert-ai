# ADR-0001: Step Functions task-token callback for human confirmation

## Status
Accepted

## Context
The agent investigation loop must pause after proposing a whitelisted fix and
wait for a human to confirm or reject it before `execute_fix` can run. Two
ways to implement that wait:

1. **DB-flag polling** — write `status = awaiting_confirmation` to the
   Alerts table, have the confirm/reject API handlers flip the flag, and have
   *something* (a poller, or the frontend re-invoking a Lambda) resume the
   workflow.
2. **Step Functions task-token callback** — the state machine enters a
   `waitForTaskToken` state, hands out an opaque token, and blocks natively
   until `SendTaskSuccess`/`SendTaskFailure` is called with that token.

## Decision
Use the Step Functions task-token callback pattern.

- The wait is enforced by AWS, not by application code re-checking a flag —
  there is no code path that can accidentally skip or race past it.
- The token itself is the mechanism `execute_fix` depends on
  (`docs/decisions/ADR-0002...` and the brief's guardrail list) — DB polling
  would require inventing an equivalent token/nonce anyway to keep
  `execute_fix` from being callable without a real human action.
- No polling infrastructure (cron, long-poll Lambda, EventBridge rule) to
  build, pay for, or get wrong.
- Execution history and current wait state are visible for free in the Step
  Functions console/API, which feeds directly into the audit-trail story.

## Consequences
- Confirm/reject API handlers need the task token, not just the alert ID —
  it must be stored (e.g. on the Alert item) when the wait state is entered,
  and treated as sensitive-ish (anyone with it can resolve that one wait).
- Local testing needs either real Step Functions (via moto, if supported) or
  a thin fake for the callback surface — slightly more setup than mocking a
  DB flag would be.
