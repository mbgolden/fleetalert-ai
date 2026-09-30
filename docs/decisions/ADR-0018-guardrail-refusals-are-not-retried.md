# ADR-0018: Guardrail refusals are not retried

## Status
Accepted. Closes a backlog item raised in the capability contract for
`execute_fix`.

## Context
`RunInvestigation` and `ExecuteFix` retry on `States.ALL`: six attempts
with exponential backoff (ADR-0001's state machine, hardened during the
enterprise review). That's right for transient faults, such as a Lambda
cold-start timeout or a DynamoDB throttle. It's wrong for a
`GuardrailViolation`: a confirmation token that doesn't match, a fix that
isn't the one proposed, an alert no longer awaiting confirmation. Those are
deterministic. Every retry fails the same way, taking a couple of minutes
of backoff and seven identical error logs to land where the first attempt
already was. They also ended up in the same `Failed` state as real
outages, so the console couldn't tell "the system broke" from "a guardrail
did its job".

## Decision
- **Each task lists a first retrier for the Lambda error type
  `GuardrailViolation` with `MaxAttempts = 0`.** The first matching retrier
  wins, so refusals are never retried, and everything else keeps the
  six-attempt backoff.
- **A matching Catch routes refusals to a new `Refused` Fail state**
  (error `GuardrailViolation`), separate from `Failed`.
- **The ExecuteFix handler records a refusal as `execution_refused`** (a
  `denied` span, and an `ExecutionRefusals` metric), not
  `execution_failed`. The alert still ends `failed`, since the fix didn't
  run.
- **A test pins the exception's class name.** The state machine matches on
  the Lambda runtime's `errorType`, which is the class name, so renaming
  `GuardrailViolation` would quietly bring the retries back.

## Consequences
- A refused execution ends in about a second, not a couple of minutes, and
  shows as a refusal in the trace, the metrics and the Step Functions
  console.
- The failed-executions alarm still fires for refusals, because
  `ExecutionsFailed` counts every Fail state. A refused execution is
  unusual enough on this demo to be worth a look.
- The coupling between the Python class name and the state machine
  definition is implicit. The test makes it explicit rather than removing
  it.
