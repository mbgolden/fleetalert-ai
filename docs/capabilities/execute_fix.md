# execute_fix

Runs a confirmed fix. This is the only `executes_action` capability, and the
last guardrail before anything happens.

| | |
|---|---|
| Safety tier | `executes_action` |
| Idempotent | **no**, so it is never retried automatically by the registry |
| Model can call it | **never** (the registry refuses to register it as agent-callable) |
| Owner | FleetAlert agents platform |

**Input:** `{ "fix_id": string, "confirmation_token": string }`

**Output:** `{ "status": "resolved", "fix_id": string }`

**Who can call it.** Only `fleetalert.agent.loop.execute_fix`, run by the
ExecuteFix Lambda, which Step Functions reaches only after a human's Confirm
resolves the task-token wait. That is the only caller passing the
`executes_action` tier. The agent loop passes `read_only` and
`proposes_action` only, so no model output can reach this capability.

**Checks, all re-verified here regardless of earlier checks**
1. The alert is `awaiting_confirmation`.
2. The token matches the one `request_confirmation` issued.
3. The fix_id matches the proposal that was confirmed.
4. The fix_id is on the whitelist. This is defense in depth, and should be
   unreachable if it fails.
5. A conditional write to `resolved`, which loses cleanly to a concurrent
   request.

Any failed check raises `GuardrailViolation`, recorded as a `failure` span
with `error_type` set so callers can tell a refusal from an infrastructure
error.

**Known failure modes**
- **Guardrail violations are not transient.** Step Functions' own task
  retry will retry them anyway, and they will fail the same way each time,
  then land in the terminal Failed state. That's safe but wasteful. A future
  change could mark `GuardrailViolation` as non-retryable in the state
  machine.
