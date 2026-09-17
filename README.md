# FleetAlert AI

Portfolio piece demonstrating agentic AI system design with real safety
guardrails: telemetry → alert → AI investigation → human-confirmed fix.
Companion piece to [PlayIt](https://github.com/mbgolden/playit) (hybrid
ML/LLM game recommender) on the same portfolio — same documentation style
(public write-up + a running ADR decision log).

**Demo constraint:** no free-text input from visitors. A fixed set of
pre-seeded synthetic alert scenarios only, to bound LLM API cost and abuse
risk on a public demo.

## Stack

| Layer | Choice |
|---|---|
| Language | Python |
| Compute | AWS Lambda + API Gateway |
| Orchestration / human-in-the-loop | AWS Step Functions (task-token callback) |
| Data | DynamoDB |
| Frontend | React, hosted on S3 + CloudFront |
| Observability | CloudWatch |
| IaC | Terraform |
| CI/CD | GitHub Actions |
| Secrets | AWS Secrets Manager / SSM Parameter Store |
| LLM | Claude API (Anthropic) |
| Testing | pytest, moto |
| Static analysis | ruff, mypy, bandit |

## Repo layout

```
backend/    Lambda handlers, agent loop, tool implementations, tests
frontend/   React app (alert list, live trace view, confirm/reject, audit log)
infra/      Terraform modules + single `demo` environment
docs/decisions/   ADR log
```

## Guardrails

See [`docs/decisions/`](docs/decisions/) for the reasoning behind each of
these. They are the point of the project, not incidental:

1. Fixed action whitelist — anything outside it routes to human support.
2. Structured tool calls only — no freeform-text-triggered actions.
3. Max 6 agent loop iterations, then forced route-to-support.
4. `execute_fix` unreachable without a valid Step Functions confirmation token.
5. Full append-only audit trail, surfaced per-alert in the frontend.

## Status

Early scaffold — see `docs/decisions/` for design decisions made so far.
Terraform is plan-only in CI for now; no resources have been provisioned.
