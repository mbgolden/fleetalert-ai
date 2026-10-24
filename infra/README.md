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

## MCP server tokens (ADR-0025)

Terraform creates `fleetalert-ai-demo-mcp-tokens` empty. Set its value by
hand (console "Plaintext", or `aws secretsmanager put-secret-value`) as JSON:

```json
{"tokens": "visitor:read_only:<32+ chars>,ops:executes_action:<32+ chars>",
 "state_key": "<64 hex chars>"}
```

Generate the secrets with `openssl rand -hex 24` for each token and
`python -c "import secrets; print(secrets.token_hex(32))"` for `state_key`.
The visitor token is meant to be published; the ops token is not. The
Lambda reads the secret once per container, so a change takes effect on
the next cold start (or redeploy the function).
