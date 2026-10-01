# FleetAlert AI

An agentic investigation system for fleet-maintenance alerts, built to show
what production guardrails around an LLM agent look like. Claude investigates
an alert by calling tools: telemetry, a knowledge base (RAG) and service
history. It then proposes a fix, and **a human has to confirm it before
anything executes**. That rule is enforced by the architecture, not just the
prompt.

- **Live demo:** https://fleetalert.10finger.dev
- **Eval results:** https://fleetalert.10finger.dev/evals
- **Write-up and architecture:** https://10finger.dev/project/fleetalert-ai

The demo uses fixed synthetic scenarios only, with no free-text input
anywhere ([ADR-0003](docs/decisions/ADR-0003-preseeded-demo-no-freetext.md)),
to bound cost and abuse on a public site.

## What it demonstrates

| | |
|---|---|
| **One engine, three entry points** | Three sources all start the same Step Functions investigation; only `entry_point` differs. They are the web UI, a simulated inbound email every 4 hours ([ADR-0016](docs/decisions/ADR-0016-simulated-email-entry-point.md)), and a rule-based detector watching live synthetic telemetry ([ADR-0020](docs/decisions/ADR-0020-autonomous-telemetry-detector.md)). The email and the detector each have a demo button too. |
| **Capabilities Engine** | Every action is a registered capability with JSON-schema input and output contracts, a safety tier, an owner and a retry policy. The model only ever gets the `read_only` and `proposes_action` tiers, so `executes_action` is unreachable from anything it says. |
| **Human in the loop, structurally** | A proposal pauses the state machine on a task-token wait. Only a human's Confirm resumes it, and the fix is re-checked (status, token, proposal, whitelist) before it runs. Unanswered proposals route to support after 2 hours. |
| **Structured traces** | Every model call, capability call, guardrail decision and human action is a span with input, output, latency, status and cost. They're grouped one trace per round and shown live in the UI. |
| **Evals** | Golden scenarios graded deterministically from the spans, 3 trials each against real Claude. They gate PRs that change agent behaviour, and recorded runs replay for free on every PR. The page linked above shows the results and what they caught. |
| **Observability and cost** | Every span also becomes a CloudWatch metric. A dashboard, four alarms, and a daily cost guard (50 rounds or $1.25 a day) sit in front of the Anthropic workspace limit. |

## How an investigation flows

```
entry point (web click · inbound email · telemetry detector)
  -> Step Functions: RunInvestigation (agent-loop Lambda)
       -> daily budget reserved (or refused before any model call)
       -> Claude tool loop (max 6 iterations), every call through the Capabilities Engine:
            get_telemetry_snapshot · search_knowledge_base · get_service_history · propose_fix
       -> guardrails: truncated output? previously rejected? whitelisted?
  -> WaitForConfirmation (task token, 2 h timeout)
       Confirm -> ExecuteFix (re-checks everything) -> resolved
       Reject  -> one knowledge-base-backed re-investigation, then route to support
       Timeout -> route to support
```

## Guardrails

Each one has a decision record in [`docs/decisions/`](docs/decisions/):

1. **Fixed action whitelist.** Anything else routes to human support
   ([ADR-0002](docs/decisions/ADR-0002-fixed-action-whitelist.md)).
2. **Schema-validated capability calls only, with safety tiers enforced by
   the registry.** No freeform text triggers behaviour
   ([ADR-0011](docs/decisions/ADR-0011-capabilities-engine-and-structured-traces.md)).
3. **Max 6 loop iterations, then route to support.** Tool calls from a
   response cut off at `max_tokens` are never run.
4. **`execute_fix` needs a human-issued confirmation token**, delivered
   through a Step Functions callback
   ([ADR-0001](docs/decisions/ADR-0001-step-functions-task-token-callback.md)).
   It isn't retried on refusal
   ([ADR-0018](docs/decisions/ADR-0018-guardrail-refusals-are-not-retried.md)).
5. **A rejected fix can't be proposed again.** There's one retry, then
   support ([ADR-0014](docs/decisions/ADR-0014-rejection-triggers-one-rag-retry.md)).
6. **Inbound email is untrusted data.** It's framed as a report, and it
   can't skip confirmation
   ([ADR-0016](docs/decisions/ADR-0016-simulated-email-entry-point.md)).
7. **A daily cost cap**, checked before any model call
   ([ADR-0017](docs/decisions/ADR-0017-span-metrics-and-daily-cost-guard.md)).
8. **An append-only trace of everything.** The only deletion is the demo
   reset ([ADR-0015](docs/decisions/ADR-0015-demo-reset-deletes-spans.md)).

## Stack

| Layer | Choice |
|---|---|
| Agent | Python 3.12, Claude API (Anthropic SDK), tool use |
| Compute and orchestration | AWS Lambda, Step Functions (task-token callback), EventBridge schedules |
| API | API Gateway HTTP API |
| Data | DynamoDB (alerts, machines, telemetry, knowledge base, traces, usage) |
| Frontend | React + TypeScript (Vite) on S3 + CloudFront, at a custom domain |
| Observability | CloudWatch Embedded Metric Format, dashboard, alarms, SNS |
| IaC | Terraform, remote state in S3 with DynamoDB locking |
| CI/CD | GitHub Actions with OIDC (no long-lived AWS keys): plan on PR, apply and deploy on merge |
| Quality | pytest + moto, ruff, mypy (strict), bandit, a capability-coverage gate, live and replay evals |

## Repo layout

```
backend/src/fleetalert/   agent loop, Capabilities Engine, tracing, metrics, budget, entry points, Lambda handlers
backend/evals/            golden scenarios, graders, live and replay harness, recorded cassettes and results
backend/tests/            unit and integration tests (moto; no AWS or API key needed)
frontend/                 alert list, live trace viewer, confirm/reject, inbound email view, Evals page
infra/                    Terraform modules and the single demo environment
docs/decisions/           ADR log (why things are the way they are)
docs/capabilities/        one contract doc per capability
docs/BACKLOG.md           known follow-ups, with the evidence that raised them
```

## Running it locally

Backend (from `backend/`, with [uv](https://docs.astral.sh/uv/)):

```bash
uv sync --group dev
uv run pytest                                  # everything, including the replay evals
uv run ruff check . && uv run mypy src evals
uv run python -m evals.run replay              # recorded trajectories, free
ANTHROPIC_API_KEY=... uv run python -m evals.run live --trials 3
```

Frontend (from `frontend/`):

```bash
npm ci
VITE_API_BASE_URL=https://<api-id>.execute-api.us-east-1.amazonaws.com npm run dev
```

The API allows `http://localhost:5173` for local development
([ADR-0007](docs/decisions/ADR-0007-defer-cors-until-final-domains.md)).

## Delivery

Work happens on a feature branch and goes through a PR. CI runs lint,
types, security checks, tests, the replay evals, the frontend build and
`terraform plan`. PRs that change agent behaviour also run the live evals.
A merge to main applies Terraform and deploys the frontend
([ADR-0013](docs/decisions/ADR-0013-deploy-on-merge-pr-checks-as-the-gate.md)).

## Decision log

| ADR | Decision |
|---|---|
| [0001](docs/decisions/ADR-0001-step-functions-task-token-callback.md) | Step Functions task-token callback for human confirmation |
| [0002](docs/decisions/ADR-0002-fixed-action-whitelist.md) | Fixed action whitelist instead of agent-generated action types |
| [0003](docs/decisions/ADR-0003-preseeded-demo-no-freetext.md) | Pre-seeded demo scenarios instead of free-text input |
| [0004](docs/decisions/ADR-0004-github-oidc-sub-claim-immutable-ids.md) | GitHub OIDC trust policy broke against immutable-ID `sub` claims |
| [0005](docs/decisions/ADR-0005-terraform-apply-via-gated-github-environment.md) | Terraform apply through a gated GitHub environment (superseded) |
| [0006](docs/decisions/ADR-0006-defer-backpressure-until-real-feed.md) | Defer backpressure between alert intake and investigation |
| [0007](docs/decisions/ADR-0007-defer-cors-until-final-domains.md) | Defer CORS configuration until final domains are known |
| [0008](docs/decisions/ADR-0008-defer-claude-api-retry-backoff.md) | Defer explicit retry/backoff around the Claude API call |
| [0009](docs/decisions/ADR-0009-custom-domain-two-phase-acm.md) | Custom frontend domain via a two-phase ACM apply |
| [0010](docs/decisions/ADR-0010-demo-data-never-exercised-the-ambiguous-scenario.md) | The demo data never exercised the ambiguous scenario |
| [0011](docs/decisions/ADR-0011-capabilities-engine-and-structured-traces.md) | A Capabilities Engine and structured traces |
| [0012](docs/decisions/ADR-0012-eval-harness.md) | Eval harness with live and replay tiers, and what its first runs found |
| [0013](docs/decisions/ADR-0013-deploy-on-merge-pr-checks-as-the-gate.md) | Deploy on merge to main, with PR checks as the gate |
| [0014](docs/decisions/ADR-0014-rejection-triggers-one-rag-retry.md) | A rejected fix triggers one knowledge-base-backed re-investigation |
| [0015](docs/decisions/ADR-0015-demo-reset-deletes-spans.md) | Demo reset is the one path that deletes trace spans |
| [0016](docs/decisions/ADR-0016-simulated-email-entry-point.md) | A simulated inbound-email entry point, and a confirmation timeout |
| [0017](docs/decisions/ADR-0017-span-metrics-and-daily-cost-guard.md) | Metrics from spans, and a daily cost guard |
| [0018](docs/decisions/ADR-0018-guardrail-refusals-are-not-retried.md) | Guardrail refusals are not retried |
| [0019](docs/decisions/ADR-0019-publish-eval-results-on-the-demo.md) | Publish eval results on the demo site |
| [0020](docs/decisions/ADR-0020-autonomous-telemetry-detector.md) | An autonomous entry point: synthetic live telemetry and a rule-based detector |
| [0021](docs/decisions/ADR-0021-migrate-to-sonnet-5-5.md) | Migrate the agent from Sonnet 5 to Sonnet 5.5, on eval evidence |
