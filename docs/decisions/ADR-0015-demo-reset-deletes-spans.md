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

## Update (2026-10-02): the detector's alert
Reset left the telemetry detector's alert (ALERT-1007, ADR-0020) untouched.
The detector creates that alert at runtime, so it isn't in the seed data,
and `reseed_demo_data` only restores what's seeded. After a reset, six
alerts were `open` and Truck 31's was still `resolved` with its old trace.

- **Reset now reopens it, as detected.** The alert keeps what the detector
  wrote (type, severity, the detection, its timestamp). It loses what the
  investigation added (proposal, tokens, rejections) and its spans. It's a
  whole-item put, like the seeded alerts get. If the detector has never
  raised anything, reset creates nothing.
- **Reopen, not delete.** Deleting would return the list to its seeded
  state, but an execution or queued message still in flight would then act
  on a missing alert. An unconditional update could recreate it as a stub,
  and a failed round would end up in the dead-letter queue. Reopening has
  the same in-flight behaviour the seeded alerts already have.
- **A normal detector run keeps an open alert's evidence.** The truck's
  stored readings are what an investigation of the reopened alert reads.
  Every other scheduled run generates normal readings, which would replace
  them and leave an open alert with nothing behind it. So when the alert is
  `open` and a run finds nothing, the run leaves the stored readings alone.
  A run that does detect something replaces both the readings and the
  alert, as before.

Found alongside it: `GET /demo/alerts` returned each alert item whole,
including `step_functions_task_token`. The token can't be used without AWS
credentials, but no client needs it, so the list now leaves it out.

