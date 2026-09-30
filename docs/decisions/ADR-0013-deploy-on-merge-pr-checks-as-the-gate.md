# ADR-0013: Deploy on merge to main, with PR checks as the gate

## Status
Accepted. Adopted at the start of the current rework (phase 0) and written
up 2026-09-30. Supersedes
[ADR-0005](ADR-0005-terraform-apply-via-gated-github-environment.md).

## Context
Under ADR-0005, every AWS change waited for a manual approval on the
`aws-apply` environment. Work had moved to one short-lived feature branch
per phase, reviewed as a PR. The approval click came after the review and
added nothing to it, and the real validation (tests, lint, type checks,
`terraform plan`, evals) already ran on the PR. The old setup had two other
problems:
- CI planned on pushes to main at the same moment the apply ran. Both
  contended for the Terraform state lock, and a live apply failed on
  "state locked".
- Deploying the frontend and applying Terraform were manual runs, so main
  and what was live could drift.

## Decision
- **Feature branch, then PR, then merge to main.** Nothing is pushed to main
  directly.
- **The PR is the gate.** `CI` (backend, frontend, and `terraform plan`
  against the real state) runs on every PR. `Evals (live)` also runs when
  agent code changes (ADR-0012).
- **Merging to main deploys automatically:**
  - `Terraform Apply (demo)` on changes under `backend/**` or `infra/**`.
  - `Frontend Deploy` on changes under `frontend/**`.
  - Both can also be run manually.
- **The `aws-apply` environment keeps the OIDC trust boundary**, which is
  still the only way to assume the apply role, but its required reviewer is
  removed.
- **The state lock is serialised, not raced.** The PR plan and the main
  apply share the concurrency group `terraform-state-demo` (queue, never
  cancel), and both wait on a held lock with `-lock-timeout=5m` rather than
  failing.
- **Seeding and the state bootstrap stay manual** (`workflow_dispatch`
  only). They are rare, and seeding resets live demo data.

## Consequences
- Once a PR is merged, the change is live within minutes, with no second
  approval step. Merging is the decision, and the PR shows the plan diff and
  eval results before it's made.
- The gate is only as strong as main's branch protection. Requiring a PR and
  the `backend`, `frontend` and `terraform-plan` checks is a repository
  setting the owner applies. `Evals (live)` stays advisory, because
  path-filtered workflows can't be required checks.
- A bad merge deploys immediately. The recovery is a revert PR through the
  same pipeline. For a single demo environment, that is an acceptable trade
  for removing the manual step.
