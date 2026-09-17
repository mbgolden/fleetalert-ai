# Terraform

Single `demo` environment — see `envs/demo/`. `terraform plan` runs in CI on
every push to `main`; `terraform apply` is manual only, run by hand once
there's a real AWS account/budget to provision against.

Remote state: S3 backend + DynamoDB lock table (added once the account
exists — not needed for `plan` against an unconfigured backend during early
scaffolding).

## Modules (planned)

- `lambda/` — one module instance per function (telemetry generator, alert
  detector, agent loop, execute fix, API handlers)
- `api_gateway/`
- `step_functions/` — investigation state machine
- `dynamodb/` — Machines, Telemetry, Alerts, KnowledgeBase, AuditLog tables
- `frontend/` — S3 + CloudFront
- `observability/` — CloudWatch dashboards + alarms
- `iam/` — one least-privilege role per function
