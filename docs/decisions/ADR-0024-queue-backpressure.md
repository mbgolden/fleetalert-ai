# ADR-0024: Queue-based backpressure for machine-generated alerts

## Status
Accepted. Supersedes
[ADR-0006](ADR-0006-defer-backpressure-until-real-feed.md), which designed
this and deferred it until there was a feed to design against. The results
are below, filled in from the recorded rerun. The worker cap was raised
from 6 to 50 once the account limit went to 1,000, and rerun (see the last
two sections).

## Context
The load test (ADR-0023) pushed 7,200 investigations an hour, each holding
a Lambda for about 6.4 s, into an account that allows 10 concurrent
Lambdas. Three things happened:
- Throughput stopped at about 4,400 an hour.
- 16% of investigations were lost without a trace, after Step Functions
  ran out of retries.
- The public API returned 503 for about six minutes, because every Lambda
  slot was taken.

Every entry point started a Step Functions execution directly, so nothing
stood between a burst of alerts and the shared concurrency pool. The only
defence was a retry policy, which copes with a blip. Under sustained
overload, retries add load and then give up.

Two constraints shaped the design:
- **The limit of 10 is account-wide.** With a limit that low, AWS doesn't
  allow reserved concurrency on a function. So "give the API its own
  slots" and "cap the agent-loop function" aren't available.
- **The human-confirmation flow must not change.** A proposal still waits
  on a Step Functions task token (ADR-0001), and a rejection still loops
  back once (ADR-0014).

## Decision
- **Machine-generated alerts go onto an SQS queue.** That covers the
  inbound email, the telemetry detector (both the schedule and the demo
  button) and load tests. They call `enqueue_investigation`, not
  `start_investigation`.
- **A worker Lambda takes them off the queue with a fixed maximum
  concurrency** (`investigation_worker_concurrency`, default 6 of the
  account's 10). The SQS event source mapping's cap is the backpressure
  control, and it works without reserved concurrency. A burst waits in the
  queue. It can't consume the slots the API and the web path need.
- **The worker runs the round itself** (`run_round`, shared with the Step
  Functions task). A round that routes to support ends there, with no
  execution. A round that produces a proposal starts the state machine at
  the confirmation wait, passing the outcome in. A new first state,
  `AlreadyInvestigated`, skips `RunInvestigation` when it's present.
- **Duplicates are harmless.** SQS delivers at least once. A second
  delivery finds the alert already past the round and re-reports its
  outcome. The execution is named after the round's trace, so Step
  Functions refuses a second confirmation wait.
- **Nothing is lost.** A round that fails returns its message to the
  queue. After three receives the message goes to a dead-letter queue,
  kept 14 days.
- **Two alarms:** one for any dead letter, and one when the oldest queued
  message has waited more than 10 minutes.
- **The web path stays direct.** A visitor clicking Investigate starts the
  execution immediately, as before. It's human-paced and gets the 4 slots
  the queue leaves free, shared with the API. Re-investigation after a
  rejection also stays in the state machine.
- **The load test can run either path** (`queue` or `direct`) and probes
  the public API throughout, so the difference is measured, not asserted.

## Consequences
- Overload becomes latency. At 7,200 an hour against a ceiling near 4,000,
  the backlog grows during the burst and drains afterwards. Alerts are
  investigated late, not lost, and the demo stays up.
- Queued alerts show `queued` in the UI until a worker picks them up.
  That's usually under a second, and longer under load.
- The cap is static. With the account's limit raised to the default 1,000,
  the cap can rise too. The next ceiling is then the model provider's rate
  limit, which this design also absorbs, because the queue doesn't care
  why workers are slow.
- There are two ways into a round now (worker and state machine task).
  They share one function, and both are tested, but it's one more seam to
  keep in mind.
- A dead-lettered message needs a person. Redrive is manual by design at
  this scale.

## Results (2026-10-01 18:08)
The level that broke the direct path was rerun through the queue: 7,200
investigations an hour for 5 minutes, with 2 s of simulated model time per
call. Report: `docs/load-tests/2026-10-01T1808-queue-7200-2000ms.json`.

| | Direct (17:12 run) | Through the queue |
|---|---|---|
| Completed | 502 of 600 | **600 of 600** |
| Lost without a trace | 98 (16%) | **0** |
| Dead letters | n/a | 0 |
| Public API during the level | about 90% of requests failed for about 6 min | **145 of 145 probes OK** |
| Lambda throttles | agent loop and API throttled | **0 on worker, agent loop and API** |
| Peak concurrency | 10 (the account limit) | **6 (the cap)** |
| Throughput | about 4,400/h | 2,510/h |
| Wait before a round began | lost ones waited forever | p50 4.6 min, p95 8.8 min, max 9.4 min |
| Round processing p50 / p95 | 6.36 s / 6.38 s | 6.36 s / 6.38 s |

- **Overload became latency.** The backlog peaked at 386 messages, the
  oldest waited 530 s, and the queue drained fully about 9 minutes after
  the burst ended.
- **The cap held.** Worker concurrency never exceeded 6, which left the
  API its slots. The backlog alarm threshold (10 minutes) was not reached.
- **Throughput came in below the prediction.** 6 workers at 6.4 s a round
  predicts about 3,400/h. The measured 2,510/h is about 4.4 workers busy
  on average. The cause wasn't investigated. The likely one is the overhead
  of SQS delivering one message per invocation. It's a tuning question
  (batch size, the cap), not a correctness one.
- **The trade is explicit.** The unprotected path was faster (about
  4,400/h) right up to the point it lost 16% of the work and took the site
  down. The queue gives up peak throughput for zero loss and a healthy API.

**Next limits, in order (as of this run):**
1. The account's Lambda concurrency: 10, against a default of 1,000. It's a
   quota request, after which the worker cap can rise by an order of
   magnitude. (Done the same day; see the next section.)
2. Then the model provider's rate limits, which this same queue absorbs.

## After the quota increase (2026-10-01): cap raised from 6 to 50
The account's Lambda concurrency limit is now 1,000, so the first limit
above is gone. The worker cap (`investigation_worker_concurrency`) goes
from 6 to 50.

**Why 50 and not 900:**
- The cap no longer protects Lambda slots. 50 of 1,000 can't starve the
  API or the web path.
- It now bounds how many model calls run at once. In production each
  worker holds an open request to the model provider, so the cap is the
  control for the provider's rate limit, which is the next ceiling.
- 50 workers at 6.4 s a round is about 28,000 investigations an hour.
  That's four times the load that broke the direct path, and still low
  enough to push past in a short load test.

**What the rerun should show:**
- 7,200/h, which built a 9-minute backlog at a cap of 6, needs about 13
  workers. It should pass straight through with no backlog.
- 36,000/h is above the new ceiling. The backlog should grow during the
  burst and drain within a couple of minutes, with nothing lost.

### Results at a cap of 50 (2026-10-01 20:57)
Reports: `docs/load-tests/2026-10-01T2057-queue-*.json`. Both levels ran
for 5 minutes with 2 s of simulated model time per call.

| | 7,200/h, cap 6 (18:08) | 7,200/h, cap 50 | 36,000/h, cap 50 |
|---|---|---|---|
| Completed | 600 of 600 | 600 of 600 | 3,000 of 3,000 |
| Lost or dead-lettered | 0 | 0 | 0 |
| Throughput | 2,510/h | **7,060/h** | **24,364/h** |
| Wait before a round began, p50 | 4.6 min | **84 ms** | 67 s |
| Wait, p95 / max | 8.8 min / 9.4 min | 181 ms / 5.8 s | 2.2 min / 2.5 min |
| End to end p50 / p95 | 4.7 min / 8.9 min | 6.4 s / 7.0 s | 73 s / 2.3 min |
| Peak backlog | 386 | 0 | 865 |
| Peak worker concurrency | 6 | 25 | 51 |
| Lambda throttles (worker, API) | 0 | 0 | 0 |
| Public API probes | 145 of 145 OK | 55 of 55 OK | 45 of 45 OK |

- **The load that broke the direct path is now ordinary.** 7,200/h passed
  straight through. The median alert waited 84 ms for a worker, where it
  had waited 4.6 minutes at a cap of 6. The 5.8 s maximum is the first few
  seconds of the burst, while SQS was still adding workers.
- **Past the new ceiling, the queue did the same job at five times the
  scale.** 36,000/h is above what 50 workers can do. The backlog reached
  865, the longest wait was 2.5 minutes, and the queue drained 2.4 minutes
  after the burst ended. Nothing was lost and the API stayed healthy.
- **The ceiling is about 24,400/h.** 50 workers at 6.4 s a round predicts
  about 28,000/h, so the workers were about 87% busy, including the ramp
  at the start. At a cap of 6 that figure was 73%, so the shortfall noted
  above shrinks as the cap grows.
- **Two readings are slightly off and not explained.** Peak concurrency
  was 51 against a cap of 50, and 25 at 7,200/h where about 13 workers
  were busy on average. Neither caused a throttle. The second is likely
  SQS starting more workers than it needs at the front of a burst.

**The next limit** is the model provider's rate limit. These rounds used
a scripted model, so 50 concurrent rounds here cost nothing. With a real
model, 50 workers means up to 50 open model requests, and the cap is the
setting to tune against that limit.
