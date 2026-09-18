# ADR-0006: Defer backpressure between alert intake and investigation

## Status
Accepted

## Context
Today, nothing produces alerts automatically. Alerts are pre-seeded
(`SEED_ALERTS`) and a visitor triggers each investigation one at a time by
clicking Investigate, which calls `POST /demo/alerts/{alert_id}/investigate`
directly. The brief's Synthetic Telemetry Generator and Rule-based Alert
Detector -- the two Lambdas that would autonomously produce new alerts on a
schedule -- are still just planned, not built.

If those two Lambdas existed and auto-triggered investigations (rather than
a human clicking a button), a real backpressure problem would exist: the
agent loop is comparatively expensive per alert -- several sequential Claude
API round trips (up to `MAX_LOOP_ITERATIONS`), each with its own latency,
cost, and rate limit -- so a burst of detected alerts arriving faster than
investigations can safely complete would either queue up invisibly inside
Step Functions/Lambda concurrency limits, get throttled with no backoff, or
silently overrun the Claude API's rate limit.

## Decision
Not implementing backpressure infrastructure now. There is no real feed to
apply it to -- the producer side (Telemetry Generator, Alert Detector) does
not exist yet, so there is nothing to observe, tune, or demo, and no way to
validate the design against real behavior. Building the queue and concurrency
controls now would mean designing blind and carrying dead infrastructure
(a queue, a DLQ, a dispatcher Lambda, another IAM role) with zero traffic
through it, which also cuts against the brief's own non-goal: "no
production-scale load handling -- this is a free-tier-bounded public demo,
not a production system."

The design below is specified now, deliberately, so that building the
Telemetry Generator and Alert Detector later is execution against an
already-reviewed plan rather than a from-scratch decision made under time
pressure.

## Design for when a real feed exists (specified now, not built)

```
Rule-based Alert Detector (Lambda)
        |
        |-- writes alert record --> DynamoDB: Alerts table   (unchanged)
        |
        `-- enqueues -----------> SQS: Alert Feed Queue
                                        |
                                        v
                          Investigation Dispatcher (Lambda)
                          SQS event source mapping, with
                          maximum concurrency set (e.g. 2-3)
                                        |
                                        v
                          states:StartExecution  ------->  (existing Step
                                                             Functions flow,
                                                             unchanged)
```

- **The backpressure control is the SQS event source mapping's maximum
  concurrency setting on the Dispatcher Lambda**, not a custom rate limiter.
  Alerts arriving faster than that cap simply wait in the queue -- SQS is
  the buffer -- rather than spamming Claude's API or exhausting Lambda/Step
  Functions concurrency.
- **A DLQ (redrive policy) on the queue** catches alerts that fail dispatch
  repeatedly (e.g. `StartExecution` throttled, malformed message) after N
  attempts, so they're inspectable rather than retried forever or dropped
  silently.
- **Visibility timeout** on the queue set longer than the Dispatcher's
  expected `StartExecution` latency, to avoid the same alert being
  dispatched twice by a redelivery race.
- **The manual "Investigate" button stays a separate, direct path** --
  `POST /demo/alerts/{alert_id}/investigate` keeps calling `StartExecution`
  directly, bypassing the queue entirely. A human-initiated investigation
  shouldn't wait behind a backlog of automatically-detected ones.
- This is purely additive upstream of the existing entry point: the Step
  Functions state machine, the agent loop, and all five guardrails are
  unchanged by this design. Only what decides *when* `StartExecution` gets
  called changes.

## Consequences
- Until the Telemetry Generator and Alert Detector are built, this remains
  an unvalidated (if reviewed) design -- flag that plainly if it's ever
  referenced as "already handled."
- When built, expect the same IAM-permission-discovery pattern documented
  in ADR-0004 and the apply saga more generally (SQS send/receive/delete
  for the detector and dispatcher, plus the dispatcher's own execution
  role) -- budget for a few rounds of `terraform plan`/`apply` surfacing
  one missing action at a time.
- The concurrency cap is a single number to tune (`maximum concurrency` on
  the event source mapping) rather than application code, which is the
  point -- it should be adjustable without touching the agent loop, the
  dispatcher, or the state machine.
