# ADR-0008: Defer explicit retry/backoff around the Claude API call

## Status
Accepted

## Context
`fleetalert.agent.loop.run_investigation` calls `client.messages.create(...)`
up to `MAX_LOOP_ITERATIONS` (6) times per investigation, with no explicit
retry or backoff around that specific call. A single transient failure --
a rate limit (429), a dropped connection, a momentary 5xx from Anthropic's
API -- currently propagates straight out of the Lambda as an unhandled
exception.

As of ADR-0006's Step Functions changes, that's no longer silent: the
`RunInvestigation` task now retries the whole Lambda invocation up to 6
times (2s backoff, doubling) before landing on the terminal `Failed` state,
and the handler marks the alert `status="failed"` on the final attempt.
So a transient Claude API blip today means: the entire investigation
restarts from scratch (a fresh Lambda invocation, a fresh loop from
iteration 1), rather than just that one API call being retried in place.

## Decision
Not adding call-level retry/backoff (e.g. enabling the `anthropic` SDK's
built-in retry support, or wrapping the call in `tenacity`) right now.
The Step Functions-level retry already added means a transient failure is
not silent or fatal -- it costs an extra full loop restart, which is
wasteful (discards whatever telemetry/KB lookups already happened that
iteration) but not incorrect, and this project has no traffic yet to
observe how often it actually matters.

Revisit this if it becomes a real problem: the concrete signal to watch
for is CloudWatch showing `RunInvestigation` retries correlating with
Claude API 429/5xx responses (visible in the structured logs added
alongside this ADR) rather than genuine bugs. At that point, the fix is
narrow and well-understood -- pass `max_retries` to the `anthropic.Anthropic`
client constructor in `fleetalert/handlers/agent_loop_handler.py` (the SDK
already implements exponential backoff for retryable errors; this is a
constructor argument, not new logic to write) -- so deferring costs
nothing but a later small change, not a redesign.

## Consequences
- A transient Claude API failure currently costs a full loop restart (up
  to `MAX_LOOP_ITERATIONS` fresh iterations) rather than a single retried
  API call -- more latency and token cost per incident than necessary, but
  bounded by the same Step Functions retry budget either way.
- If Claude API errors turn out to be the dominant cause of
  `RunInvestigation` retries once there's real traffic to observe, adding
  `max_retries` to the Anthropic client is the fix -- not a bigger change.
