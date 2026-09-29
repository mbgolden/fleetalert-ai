# ADR-0011: A Capabilities Engine and structured traces

## Status
Accepted

## Context
Before this change the agent loop called a hardcoded `if/elif` dispatcher
(`agent/tools.py`) against a static list of tool schemas. The guardrails that
did exist were scattered:

- Input validation was added per tool, after live failures. Claude called
  `propose_fix` without `fix_id`, which crashed a run, and later with only
  `fix_id`, which showed a half-empty proposal. Each fix covered one tool.
- The only boundary between "things the model may do" and "things that
  execute" was that `execute_fix` wasn't in the tool list, a convention
  rather than an enforced rule.
- There was no retry policy at the capability level.
- Tracing was a flat audit log: one row per event, no hierarchy, no latency,
  no status, and no way to tell which model call led to which tool call.

Adding a second entry point (the scheduled email method) on top of that
would have meant either copying the loop's glue or leaving the email path
without guardrails.

## Decision

### Capabilities Engine
Every action registers a `Capability`. The contract fields are: `name`,
`input_schema`, `output_schema`, `safety_tier`, `idempotent`, `owner`,
`handler` and `agent_callable`. `CapabilityRegistry.invoke` is the only way
to run one, and it enforces the following for every caller:

1. **Schema validation of input before the handler, and of output after.**
   Input errors return to the model as a correctable tool error. A handler
   that breaks its own output contract fails loudly, because that is a bug
   and is not retried.
2. **A safety-tier gate.** Each caller passes the tiers it may use. The
   agent loop passes `read_only` and `proposes_action` only, so
   `executes_action` is structurally unreachable from model output. Only
   the ExecuteFix path passes `executes_action`.
3. **Retry once with backoff**, only for `idempotent` + `read_only`
   capabilities. The failed attempt is traced as `retry`. Nothing that
   proposes or executes is ever retried automatically.
4. **A trace span per attempt.**

The agent loop builds its tool list from the registry
(`agent_tools()`) and invokes through it. It no longer imports tool
functions.

### Structured traces
A Traces table replaces the flat AuditLog. There is **one trace per
investigation round**, and a rejection starts a new trace whose root span
records `previous_trace_id`. Spans have `parent_span_id`, `status`,
`latency_ms`, `actor`, `entry_point`, and token and cost attributes. The
tree for a round looks like this:

```
investigation (root: outcome, total latency, tokens, estimated cost)
├── investigation_started (lifecycle)
├── model_call (per iteration: stop reason, tool calls, text, tokens, cost)
│   └── <capability> (input, output, status, latency, safety tier)
├── guardrail.whitelist / guardrail.not_previously_rejected (decision)
├── request_confirmation (capability, system)
├── awaiting_human_confirmation (lifecycle)
├── confirm | reject (human_action)
└── execute_fix (capability) | route_to_support (decision)
```

Spans are append-only: a conditional put refuses to overwrite one. The
demo's Reset Alerts is the only path that deletes them. Confirmation and
task tokens are redacted before a span is written, because the trace API is
public.

### Deviations from the brief, deliberately
- **`name` + `kind` instead of `capability_name`.** The brief also wants
  agent decisions and human actions traced, and those aren't capabilities.
  One span schema covers all of them, and `kind = "capability"` identifies
  capability spans.
- **`agent_callable` is separate from `safety_tier`.** `request_confirmation`
  is `proposes_action` like `propose_fix`, but letting the model call it
  directly would skip the whitelist and already-rejected checks. Tier
  answers "how dangerous is this". Callability answers "who may start it".
  The registry refuses to register an agent-callable `executes_action`
  capability at all.
- **`machine_id` is not a model input.** The brief's signatures include it,
  but machine scope comes from the investigation context, so the model can't
  point a read at another machine.

## Found along the way
While restructuring the entry check, an older retry bug surfaced. On a
crashed attempt the Lambda handler marks the alert `failed`, but the
re-entry check only accepted `open` or `investigating`. So every Step
Functions retry was refused as a "duplicate" and simply reported "failed".
The six-retry policy had never actually re-run an investigation. The entry
check now accepts `failed`, and a test drives that path.

## Consequences
- **A new capability** is a registration plus a test plus a contract doc
  (`docs/capabilities/`). CI's `check_capability_coverage.py` fails the
  build if either of the last two is missing. Every caller, including the
  upcoming email and autonomous methods, gets validation, tier gating,
  retries and tracing without extra code.
- **`jsonschema` is a runtime dependency**, and it pulls in the compiled
  `rpds-py`, so the Lambda build now pins `x86_64-manylinux2014` /
  Python 3.12 explicitly.
- **The old AuditLog table** stays until the frontend moves to `/trace`. In
  the meantime `/audit` is derived from spans, so the current UI keeps
  working.
