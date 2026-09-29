# request_confirmation

Moves a whitelisted proposal to `awaiting_confirmation` and issues the
confirmation token that the human's Confirm must present. Step Functions'
`WaitForConfirmation` task-token wait follows from this state (ADR-0001).

| | |
|---|---|
| Safety tier | `proposes_action` |
| Idempotent | **no**, because it issues a new token |
| Model can call it | **no**, it is system-only |
| Owner | FleetAlert agents platform |

**Input:** the same shape as `propose_fix` (`fix_id`, `description`,
`confidence`).

**Output:** one of two shapes:
- `{ "status": "awaiting_confirmation", "fix_id", "confirmation_token" }`
- `{ "status": "superseded", "fix_id" }`

The token is redacted from trace spans.

**Why the model can't call it.** It sits in a tier the agent may use, but
it is not agent-callable. Only the loop invokes it, and only after the
whitelist and already-rejected checks pass. Letting the model call it would
skip those checks.

**Guarantees**
- **Atomic.** The status change is conditional on the alert still being
  `investigating`. If a retried Step Functions attempt arrives after an
  earlier one finished, it gets `superseded` back instead of overwriting the
  winner.

**Known failure modes**
- **`superseded` is a normal outcome under retries.** The caller reports the
  alert's current state.
