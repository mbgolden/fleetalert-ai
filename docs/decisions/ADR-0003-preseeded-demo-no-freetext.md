# ADR-0003: Pre-seeded demo scenarios instead of free-text input

## Status
Accepted

## Context
The public demo needs some way for a visitor to trigger the agent
investigation loop. The natural choice for an "AI assistant" demo is a
free-text box — but this demo makes real LLM API calls per investigation,
and is publicly reachable with no auth.

## Decision
Visitors can only pick from a fixed set of 4–6 pre-seeded synthetic alert
scenarios (`GET /demo/alerts`). There is no free-text input anywhere in the
frontend, and no API endpoint accepts arbitrary visitor-authored text that
reaches the LLM.

## Consequences
- Bounds LLM API cost to (number of seeded scenarios) × (max loop
  iterations), regardless of traffic — the worst case is fully known in
  advance rather than depending on visitor behavior.
- Removes prompt-injection-via-visitor-input as an attack surface entirely;
  the only text reaching the model comes from seeded telemetry/KB data
  Michael controls.
- Trades away "looks like a real assistant" flexibility for something that's
  actually safe to leave running unattended on a public URL. The write-up
  should be explicit that this is a deliberate demo-scoping decision, not a
  limitation of the underlying architecture.
