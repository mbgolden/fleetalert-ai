# ADR-0020: An autonomous entry point: synthetic live telemetry and a rule-based detector

## Status
Accepted (phase 7).

## Context
With the web UI and the inbound email (ADR-0016), every investigation still
started because a person, or a person's email, said something was wrong.
In the brief's architecture, telemetry flows in and the system notices
problems on its own. Until now the telemetry was seeded history, and
nothing watched it.

Two things were worth keeping in mind:
- **Detection and diagnosis are different jobs.** Detecting "is a reading
  out of range" is cheap, deterministic and easy to explain. Only the "why"
  needs a model.
- **The demo can't depend on a real fleet**, so live telemetry has to be
  generated, and generating it must not leak the answer to the detector or
  the model.

## Decision
- **A generator writes live synthetic telemetry.** Truck 31 (M-1004),
  a machine with no seeded alerts, is the detector's own. Each run
  generates its last 3 hours of readings, anchored to now, from one of
  four profiles: normal running, a coolant leak, a sensor glitch, or oil
  pressure decline. Anomalies start an hour before now, so the readings
  also show what happened afterwards. A glitch only looks like a glitch if
  the next reading is back to normal.
- **A rule-based detector checks the readings.** The rules are fixed
  thresholds, `coolant_temp_c >= 105` and `oil_pressure_psi <= 25`, and
  severity escalates when 3 or more readings trip. The detector sees only
  readings, never the profile name, so a miss or false alarm would be a
  real one. Normal readings raise nothing and cost nothing.
- **A tripped rule reopens ALERT-1007** through the same intake path as the
  email (`fleetalert.intake`: atomic claim, busy and budget checks, the last
  3 rounds kept) and starts the same investigation with
  `entry_point="autonomous"`. The alert's time is the first tripped reading,
  so the telemetry capability's window is centred on the anomaly.
- **The model gets the finding, framed as facts only**: which rule tripped
  and on how many readings, never a guessed cause.
- **Triggers:**
  - An EventBridge rule every 4 hours, rotating through normal, anomaly,
    normal and so on. Half the scheduled runs are healthy.
  - A **Run telemetry detector** button that always generates an anomaly,
    so a visitor gets something to watch.
  - Both are held while the last alert is being handled. The detector
    checks that before generating, so new readings never land inside an
    in-flight investigation's evidence window.
- **Generated readings stay bounded.** Each run replaces the truck's
  readings, so two runs minutes apart can't interleave two stories. The
  readings also carry a 2-day `expires_at` (a TTL on the telemetry table),
  and the telemetry capability strips storage-only fields before the model
  sees them.
- **An eval scenario, `autonomous-leak`**, runs the detector at a fixed
  time before investigating, so every trial and recording sees identical
  readings.
- **Detector runs are a metric** (`DetectorRuns` by result), shown on the
  dashboard.

## Consequences
- The demo now covers the whole flow: telemetry → detection → an
  investigation nobody asked for → a human decision. All three entry points
  share one engine, and the trace viewer tags each round with its source.
- The schedule adds at most 3 investigations a day (half its runs are
  healthy), within the daily cost guard (ADR-0017).
- The detector is intentionally naive. Real detection would need per-machine
  baselines, rate-of-change rules and alert de-duplication, and it's where
  ADR-0006's queue and backpressure would come in. The seam for that is
  `detect()`.
- Reset Alerts doesn't touch ALERT-1007 or the truck's readings. They're
  live data, not seed data, and the next run replaces them anyway.
