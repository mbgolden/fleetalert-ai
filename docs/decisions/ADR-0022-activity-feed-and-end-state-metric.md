# ADR-0022: A cross-alert activity feed and an end-state metric

## Status
Accepted.

## Context
Every decision and end state was already recorded as a span (ADR-0011): the
guardrail checks, proposals, human confirms and rejects, routings with
their reasons, executions, failures and refusals. But there were only two
ways to see them:
- **One alert at a time**, on that alert's page.
- **As CloudWatch totals.** These need an AWS console login, and the
  dashboard had no direct "how did alerts end" view. Resolutions only
  showed up as successful `execute_fix` capability calls.

Nothing answered "what has the system decided lately, across everything"
for someone looking at the demo, including from a phone.

## Decision
- **An Activity page (`/activity`), backed by `GET /demo/activity`.**
  `fleetalert.activity` turns spans into feed events: guardrail decisions,
  proposals, human actions, and end states (resolved, routed to support
  with a readable reason, failed, refused). Model calls and evidence reads
  stay on the per-alert trace. The page shows:
  - today's end-state counts
  - filters: all, end states, guardrails, people, proposals
  - one row per event with the alert, machine, entry point and time,
    linking to the alert's trace

  It refreshes every 20 seconds while visible.
- **Built from spans, like everything else.** The feed is a view of the
  same records the trace viewer, metrics and evals read, so it can't
  disagree with them. With a handful of alerts it's one index query per
  alert, so no new table or index is needed.
- **Repeated failures merge into one row.** A failing Step Functions task
  records a failure span on every retry attempt. Consecutive identical
  events in one trace collapse into one row with a count (×5).
- **An `AlertEndStates` metric** (by end state, and entry point as a
  value) is emitted for resolved, routed to support and refused. There's a
  new "Alert end states" dashboard panel. Failures are counted from Step
  Functions' own `ExecutionsFailed` on the same panel, because the span
  count repeats per retry.

## Consequences
- A visitor or reviewer can watch the guardrails work across the whole
  system, with no AWS access needed. The dashboard answers "how many
  resolved, routed or failed" directly.
- The feed scans every alert's spans on each request. That's fine for a
  fixed demo. A system with many alerts would need a time-ordered index,
  or a projection written as spans arrive.
- Routing reasons are mapped to readable text in one place
  (`activity.ROUTING_REASONS`). A new reason shows up in the feed in raw
  form until it's added there.
