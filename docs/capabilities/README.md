# Capability contracts

Every action in FleetAlert goes through the Capabilities Engine
(`backend/src/fleetalert/capabilities/`). Each capability registers a
contract, which the registry enforces on every call:

| Field | Meaning |
|---|---|
| `input_schema` / `output_schema` | JSON Schema, validated on **every** call (input before the handler runs, output after) |
| `safety_tier` | `read_only`, `proposes_action` or `executes_action`. Each caller states the tiers it may use |
| `idempotent` | Whether repeating the call is safe. Only `idempotent` + `read_only` capabilities are retried automatically (once, with backoff) |
| `agent_callable` | Whether it is offered to the model as a tool. `executes_action` capabilities can never be |
| `owner` | Who to talk to about changing the contract |

| Capability | Tier | Idempotent | Model can call it | Caller |
|---|---|---|---|---|
| [get_telemetry_snapshot](get_telemetry_snapshot.md) | read_only | yes | yes | agent loop |
| [search_knowledge_base](search_knowledge_base.md) | read_only | yes | yes | agent loop |
| [get_service_history](get_service_history.md) | read_only | yes | yes | agent loop |
| [propose_fix](propose_fix.md) | proposes_action | yes | yes | agent loop |
| [request_confirmation](request_confirmation.md) | proposes_action | no | **no** | agent loop (system) |
| [execute_fix](execute_fix.md) | executes_action | no | **never** | ExecuteFix Lambda |

## What every capability gets for free

These come from the registry, not from each capability:

- **Unknown names, schema violations and tier violations** come back as
  structured errors, not exceptions. When the model is the caller, the error
  goes back to it as a tool error it can correct, inside the same bounded
  loop.
- **Retry once with backoff** for idempotent reads. The failed attempt is
  traced with status `retry`. Nothing else is ever retried automatically.
- **A trace span per attempt**, recording input, output, status (`success`,
  `failure`, `retry` or `denied`), latency, safety tier and actor.
  Confirmation and task tokens are redacted before the span is written.
- **Output contract checks.** A handler that returns something outside its
  own output schema fails loudly instead of feeding the model bad data.

## Adding a capability

1. Write the handler and register a `Capability` in `capabilities/builtin.py`.
2. Add a test that invokes it **by name** through the registry.
3. Add `docs/capabilities/<name>.md`.

CI (`scripts/check_capability_coverage.py`) fails the build if step 2 or 3
is missing.
