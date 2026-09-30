# ADR-0005: Terraform apply through a gated GitHub environment

## Status
Superseded by [ADR-0013](ADR-0013-deploy-on-merge-pr-checks-as-the-gate.md).
Written after the fact (2026-09-30). This slot was reserved when the
decision was made on 2026-09-17, but the write-up was never finished.

## Context
The project started plan-only: CI ran `terraform plan` with a read-only
OIDC role, and nothing was provisioned. Once real infrastructure was
needed, applies still had to be controlled. The options were a human
running `terraform apply` from a laptop, which leaves no audit trail and
needs long-lived local credentials, or CI.

## Decision
- **Apply runs in GitHub Actions, never from a laptop.**
- **Two roles:**
  - A read-only plan role, `AWS_ROLE_ARN`.
  - A separate apply role, `AWS_APPLY_ROLE_ARN`. Its OIDC trust is limited
    to the `aws-apply` GitHub environment subject, wildcarded per ADR-0004.
- **The `aws-apply` environment required a reviewer's approval** before any
  job using it could start. That gate covered every workflow able to change
  AWS: Terraform apply, frontend deploy, demo seeding and state bootstrap.
- **The apply role is narrow by resource but wide by action.** It is limited
  to the `fleetalert-ai-*` name prefix, with `dynamodb:*`, `lambda:*` and
  so on inside it, because its only job is provisioning this project.

## Consequences
- Every change to AWS waited for a manual approval. This worked from the
  GitHub mobile app, but it made the human click the real gate rather than
  the code review.
- CI planned on every push to main at the same time as the apply ran. The
  two contended for the Terraform state lock, and one of them failed. That,
  plus the approval friction, led to ADR-0013.
