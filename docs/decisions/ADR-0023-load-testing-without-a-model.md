# ADR-0023: Load testing the live pipeline, without calling a model

## Status
Accepted. The results are below, filled in from the recorded runs.

## Context
The demo runs at a handful of alerts a day, so nothing in it had been
measured under volume. Feedback from a hiring conversation named exactly
that gap: experience with traffic volume. The honest response is to
measure, not to describe the design as if it scaled:
- How fast can the pipeline take in and finish investigations?
- What breaks first?
- What does the system do when it's pushed past that point?

Calling Claude at load test volumes would cost real money and measure
Anthropic's rate limits rather than this system. The model is also the
one part whose cost and latency are already measured, by the evals.

## Decision
- **Real pipeline, scripted model.** A generator Lambda creates throwaway
  `LT-` alerts and starts real Step Functions executions at a set rate.
  The agent-loop Lambda, the Capabilities Engine, DynamoDB reads and
  writes, the guardrails, the trace spans and the metrics all run as in
  production. Only the model is swapped for `StubModelClient`, a fixed
  three-step script: read telemetry, search the KB, propose a fix that
  isn't whitelisted. So every round ends at routed to support, instead of
  waiting two hours for a human.
- **The stub can't leak into real traffic.** It needs both a `load_test`
  flag in the execution input and an `LT-` alert id. Only the generator
  sets either, and no public route, email or detector run can.
- **The demo is isolated:**
  - Load-test rounds use their own daily usage row (`<day>#loadtest`), so
    they still exercise the budget's conditional write but never spend the
    demo's budget.
  - `LT-` alerts are excluded from the alert list and the Activity feed.
  - Each level is deleted afterwards.
  - Metrics carry `EntryPoint=loadtest`, so the dashboard separates them.
- **Measured from the traces.**
  - Queue time: from `StartExecution` to the round's first span.
  - Processing time: the round's own latency.
  - End to end: both together.
  - Throughput: rounds completed per hour of wall time.
  - Also recorded: start errors, failures, and the agent-loop Lambda's
    throttles, errors and peak concurrency from CloudWatch.
- **Run by a "Load test" GitHub workflow.** It runs levels of
  `rate_per_hour:minutes`, by default 1,000/h for 5 min, 10,000/h for
  10 min and 36,000/h for 5 min. Each level drains, then a report is
  written and the level is cleaned up. Reports are committed to
  `docs/load-tests/`.

## Found while building it
**`list_alerts` read only the first page of its DynamoDB scan.** With
7 alerts that never mattered. During a load test, the alerts table grows to
thousands of items, so the demo's alert list would have started dropping
alerts once a scan crossed 1 MB. Scans now follow every page.

## Consequences
- The pipeline has measured numbers behind it, not just a design.
- A load test briefly shares the agent-loop Lambda and Step Functions with
  the live demo. Run it when nobody is demoing. That contention is part of
  what the test measures.
- The stub makes model latency zero. Real rounds add a few seconds of
  model time each (ADR-0021), which affects concurrency, not throughput
  limits elsewhere. The report keeps the two apart.

## Results
_Filled in from `docs/load-tests/` after the first runs._
