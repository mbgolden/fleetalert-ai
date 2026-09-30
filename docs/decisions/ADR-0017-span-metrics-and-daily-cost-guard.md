# ADR-0017: Metrics from spans, and a daily cost guard

## Status
Accepted (phase 6).

## Context
The demo is public and calls a paid model. Since phase 5 it also runs
unattended: an email arrives every 4 hours whether anyone is watching or
not. The budget for the whole project is $50 a month. Before this change,
three things were missing:
- **No aggregate view.** Traces (ADR-0011) show one investigation in
  detail, but nothing showed how many investigations ran today, what they
  cost, how often guardrails fired, or whether anything was failing.
- **No spending limit inside the app.** Nothing stopped a visitor
  clicking Investigate, Reset and Simulate email in a loop. The only
  backstop was the Anthropic workspace limit, which stops everything
  abruptly, including the scheduled email.
- **No alerting.** A failed execution or a surge in cost would only be
  noticed by someone happening to look.

## Decision

### Metrics come from spans
`Tracer.record` writes the span, then `fleetalert.metrics` turns it into
CloudWatch Embedded Metric Format lines. Those are structured JSON log
lines that CloudWatch converts into metrics, with no `PutMetricData` calls
and no extra IAM. The mapping from span to metric (namespace `FleetAlert`):

| Span | Metric | Dimensions |
|---|---|---|
| Round root | `Investigations`, `InvestigationCostUSD`, `InvestigationLatencyMs`, `ModelCalls`, `InputTokens`, `OutputTokens` | none, `EntryPoint`, `Outcome` |
| Capability call | `CapabilityCalls`, `CapabilityLatencyMs` | `Status`; `Capability` + `Status` |
| Guardrail refusal | `GuardrailBlocks` | none, `Guardrail` |
| Route to support | `RoutedToSupport` | none, `Reason` |
| Human action | `HumanActions` | `Action` |
| Execution failure | `ExecutionFailures` | none |

Spans stay the single source of truth, so a metric can't disagree with the
trace it came from. Dimensions are kept low-cardinality: never alert, trace
or span ids. Metrics are only emitted inside Lambda, never in tests or
evals.

### A daily cost guard
- **One DynamoDB row per UTC day** (the `usage` table, with a 90-day TTL).
  It counts investigation rounds and the estimated spend.
- **Every round reserves a slot before its first model call.** The
  reservation is one conditional write, so two concurrent rounds can't both
  slip past a cap. A refused round ends immediately: a failed
  `guardrail.daily_budget` span, then routed to support with reason
  `daily_budget_exhausted`. No model is called.
- **Each round adds its estimated cost when it ends.**
- **The caps:** 50 rounds or $1.25 of estimated spend per UTC day,
  whichever comes first. Both are Terraform variables, passed to every
  Lambda.
- **The entry points check first, for a friendlier answer.** Investigate
  returns 429 with a message, the email button and the schedule skip, and
  the UI shows today's usage. The check in the loop is the one that
  actually enforces the cap, including on Step Functions retries.

### Dashboard, alarms and a topic
- **A CloudWatch dashboard (`fleetalert-ai-demo`)** shows:
  - investigations by entry point and by outcome
  - spend per day against the cap
  - latency p50 and p90
  - capability calls by status, and tokens
  - guardrail blocks, and routings to support by reason
  - human actions
  - Step Functions executions
  - the state of every alarm
- **Four alarms feed an SNS topic.** The owner subscribes an email address
  by hand, so no address lives in the repo.
  - Spend reaches 80% of the daily cap, over a rolling 24 hours.
  - The cost guard refused a round.
  - A capability call was denied on tier. This should never happen, so a
    single one is worth waking up for.
  - A Step Functions execution failed.

## Consequences
- **Spend is bounded inside the app.** At the cap every day, the site
  costs about $37.50 a month. Evals use their own API key, at a few dollars
  a month. The Anthropic workspace limit remains the hard stop above both.
- **Spend is an estimate.** It comes from token counts and the pricing
  table in `fleetalert.pricing`, not from Anthropic's billing. A model
  missing from that table estimates as zero, so adding a model means adding
  its price. The eval harness notes this too (ADR-0012).
- **The cap is per UTC day, but the spend alarm looks at a rolling 24
  hours.** Close to midnight the alarm can fire while the cap has already
  reset. That's harmless for an early warning.
- **A refused round leaves its alert routed to support until someone
  presses Reset.** That's the honest end state for "no automated answer
  available", and the same one every other refusal uses.
- **CloudWatch costs stay within the free tier**: a handful of custom
  metrics, four alarms and one dashboard.
