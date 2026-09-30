# ADR-0015: Demo reset is the one path that deletes trace spans

## Status
Accepted. Built as the "Reset Alerts" button, adapted to traces when
AuditLog was replaced (ADR-0011), and written up 2026-09-30.

## Context
Traces are append-only (ADR-0011). `put_span` refuses to overwrite, and
nothing in the investigation path deletes. But the public demo has five
fixed alerts, and once visitors have investigated them all, there is nothing
left to try. A reset has to return alerts to `open`, and an `open` alert
next to an old trace saying "fix executed" contradicts itself on the page.

## Decision
- **`POST /demo/reset`** (the frontend's "Reset Alerts" button) calls
  `reseed_demo_data`, which is also what the manual seed workflow runs. It
  re-puts machines, knowledge base entries, telemetry and alerts, and deletes
  every span for the seeded alerts.
- **`clear_spans_for_alert` is the only delete in the Traces repository.**
  Its docstring and this ADR mark it as demo-only.
- **Reset changes data, not actions.** It never calls `execute_fix` or
  touches Step Functions. An execution still in flight for a reset alert
  loses its next conditional status write (the status is no longer the one
  it expects), so it can't overwrite the reset or execute anything.

## Consequences
- Append-only holds for the investigation path, but not for the demo as a
  whole. A production system would keep traces and archive or version the
  alert instead of resetting it.
- Anyone can wipe demo history. That's acceptable for synthetic data. The
  public API has no other delete.
- Reset is also how new seed data reaches the live site, for example after
  the cabin-drift telemetry change in ADR-0012.
