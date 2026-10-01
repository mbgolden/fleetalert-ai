# get_telemetry_snapshot

Readings for the alert's machine in a window around when the alert fired.

| | |
|---|---|
| Safety tier | `read_only` |
| Idempotent | yes (retried once on failure) |
| Model can call it | yes |
| Owner | FleetAlert agents platform |

**Input:** `{ "window_minutes": integer 1-180 }`. No other fields are
allowed.

**Output:** `{ "readings": [ { machine_id, timestamp, signal_readings: {...} } ] }`,
in time order. The signal names depend on the machine type:
- Diesel engines report `coolant_temp_c`, `coolant_level_pct`,
  `oil_pressure_psi` and `rpm`.
- Refrigeration units report `cabin_temp_c` (an independent cabin probe),
  `controller_reading_c` (the unit controller's own return-air sensor),
  `setpoint_c`, `compressor_current_a` and `compressor_state`.

Readings the autonomous detector generates for Truck 31 (M-1004) carry
an `expires_at` for DynamoDB TTL. Storage-only fields like that are
stripped before the model sees them; only `machine_id`, `timestamp` and
`signal_readings` are returned (ADR-0020).

**Guarantees**
- **Scoped to the alert's machine.** The machine comes from the
  investigation context, never from model input (`machine_id` is not an
  accepted field), so the model can't read another machine's telemetry.
- **Deterministic for the demo.** Seeded readings are generated without
  randomness, so evals see the same evidence every run (ADR-0010). The
  detector's live readings are deterministic too, for a given profile and
  time. Evals pin the time.

**Known failure modes**
- **Empty window.** An empty `readings` list is a valid answer ("no data"),
  not an error. The agent should say so rather than guess.
- **DynamoDB throttling or network errors.** Retried once, then returned to
  the model as a tool error.
- **Numbers are `Decimal`.** DynamoDB returns them that way, and they are
  encoded as JSON numbers before reaching the model. Missing this crashed
  every telemetry read once it was seeded; see the hotfix in the git log.
