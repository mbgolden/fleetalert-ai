# Frontend

Vite + React + TypeScript SPA, served from S3 + CloudFront at
https://fleetalert.10finger.dev. It's AWS-hosted end to end, unlike the
portfolio's Next.js site.

## Views

- **Alerts (`/`)**: the project overview, today's demo budget, and the
  alert list. Email and autonomous alerts are marked with their entry point.
- **Alert detail (`/alerts/:alertId`)**:
  - the inbound email or the detector's finding that raised the alert
  - the live trace viewer: one card per round, capability calls nested
    under the model call that made them, guardrail decisions, human
    actions, cost and latency
  - Confirm and Reject controls on a proposed fix
- **Evals (`/evals`)**: recorded eval runs, built from
  `backend/evals/results` and `backend/evals/scenarios.json` at build time
  ([ADR-0019](../docs/decisions/ADR-0019-publish-eval-results-on-the-demo.md)).

The header has the three demo triggers: **Simulate inbound email**, **Run
telemetry detector**, and **Reset Alerts**. There's no free-text input
anywhere
([ADR-0003](../docs/decisions/ADR-0003-preseeded-demo-no-freetext.md)):
every action is a button.

## Local development

```bash
npm ci
VITE_API_BASE_URL=https://<api-id>.execute-api.us-east-1.amazonaws.com npm run dev
```

The API's CORS allows `http://localhost:5173`. `npm run build` type-checks
(`tsc`) and then builds.
