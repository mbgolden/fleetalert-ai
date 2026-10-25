# ADR-0026: MCP as a fourth entry point, declared by an allowlisted header

## Status
Accepted (2026-10-25)

## Context
Every investigation round carries an `entry_point` (web, email, autonomous,
loadtest) from the moment it starts: the state machine input, the trace's
root span, the Activity feed and the trace viewer's chip all show it, and
the eval scenarios select on it. The hosted MCP server (ADR-0025) starts
rounds through the same `POST /demo/alerts/{id}/investigate` route the web
UI uses, so those rounds were indistinguishable from a visitor's click.
The whole point of "one engine, N ways in" is that each way is visible.

## Decision
- **A new `EntryPoint.MCP`** (`"mcp"`), alongside the existing four.
- **The caller declares it with a header**, `x-fleetalert-entry-point: mcp`.
  Only values in a small allowlist (today just `mcp`) are honoured; any
  other value, or no header, is the web path. A caller cannot invent an
  entry point or impersonate the scheduled ones (`loadtest` has its own
  budget scope, so it must stay unreachable from the public API).
- **No new route.** The MCP server is a client of the demo API and stays
  one; it just says who it is. The 202 response echoes the entry point so
  the client can show it.
- **The frontend gains an `entry-mcp` chip colour** (amber). The trace
  viewer, Activity feed and evals page already render chips from the
  value, so nothing else changes there.
- fleetalert-mcp v0.3.0 sends the header from `start_investigation`.

## Consequences
- An investigation started from Claude Code shows "via mcp" in the trace
  and as `mcp` in the Activity feed, and the metrics carry the dimension.
- The header is trust-on-declaration. That is fine because the only thing
  it changes is a label; budget and guardrails are the same on every path.
  If an entry point ever carried privileges, it would need the governor
  key behind it, not a header.
- Email and detector demo buttons keep their own entry points; the MCP
  tools that trigger them (`simulate_inbound_email`, `run_telemetry_detector`)
  are not tagged, since the round they start is the email's or detector's.
