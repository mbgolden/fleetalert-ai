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

## First run (2026-10-01): two findings before any numbers
The first run never got past level 1, and the workflow failed after 45
minutes with an AWS CLI error. The investigations themselves all
completed (83 of 83, routed to support), but each one had run three times,
exactly 15 minutes apart.

**1. A client retry re-ran a non-idempotent operation.**
- The workflow invoked the generator synchronously and waited for its
  reply. The run lasted about 5 minutes, during which the connection
  carried no traffic.
- The connection was most likely dropped somewhere along the way: the
  generator had finished its starts on time, but the CLI never received
  the reply.
- The CLI waited out its 15-minute read timeout and retried the
  invocation, so the whole load was generated again. That happened three
  times in total, then the CLI exited with 255.
- **Fixes:**
  - The workflow now starts the generator asynchronously, and Lambda's own
    async retries are set to zero.
  - The generator claims its label with a conditional write before doing
    anything, so a second start of the same run is refused.
  - The workflow polls a short, safely-retryable `report` call until the
    generator records itself done and the queue has drained.
  - Leftovers from failed runs are cleaned up at the start of every run.

**2. Every DynamoDB call opened a new connection.**
- The traces gave a "before" measurement even though the run failed. 249
  completed rounds with no model call took **p50 2,317 ms, p95 3,002 ms**.
  Single telemetry and KB steps took about 160 ms each, roughly 80 ms per
  DynamoDB call, where single-digit milliseconds is normal.
- `get_dynamodb_resource()` built a new boto3 resource on every call, so
  every request (each span write, each query) set up a fresh HTTPS
  connection, on a 256 MB Lambda with a fraction of a CPU.
- **Fix:** the resource and the Step Functions client are now cached per
  Lambda container, so connections are reused. It's the only performance
  change in the rerun, so the difference is attributable to it.
- Locally, the same change cut the backend test suite from 36 s to 23 s.

## Results
_Filled in from `docs/load-tests/` after the rerun._
