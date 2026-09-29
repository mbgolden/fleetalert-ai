# get_service_history

Past service events for the alert's machine.

| | |
|---|---|
| Safety tier | `read_only` |
| Idempotent | yes (retried once on failure) |
| Model can call it | yes |
| Owner | FleetAlert agents platform |

**Input:** `{}`. It takes no parameters, because the machine comes from
context.

**Output:** `{ "service_history": [ { event_id, date, description } ] }`

**Guarantees**
- **Scoped to the alert's machine.**
- **Read-only.** It never changes the machine record.

**Known failure modes**
- **No history.** A machine with no history returns an empty list, which is
  a valid answer and not an error.
- **Extra fields are rejected.** If the model sends any, the registry
  returns a schema error for it to correct.
