# ADR-0004: GitHub OIDC trust policy broke against immutable-ID `sub` claims

## Status
Accepted (documents a real failure encountered during the build, not a
forward-looking design choice)

## Context
The `terraform-plan` CI job authenticates to AWS via GitHub's OIDC provider
(no long-lived AWS keys in CI). The IAM role's trust policy was written
using the standard, widely-documented pattern: an OIDC `Federated` principal
for `token.actions.githubusercontent.com`, condition-scoped with
`StringLike` on `token.actions.githubusercontent.com:sub` matching
`repo:mbgolden/fleetalert-ai:ref:refs/heads/main`.

The first CI run after wiring this up failed on every retry with:

```
Error: Could not assume role with OIDC: Not authorized to perform sts:AssumeRoleWithWebIdentity
```

## Diagnosis
The trust policy, the OIDC provider registration, and its audience list
were all individually correct — confirmed by inspection three separate
times. The AWS account is standalone (no AWS Organizations SCP could be
involved). CloudTrail's `errorMessage` for this call is deliberately
uninformative (`"Not authorized to perform sts:AssumeRoleWithWebIdentity"`,
by design, to avoid leaking federation details to probing attackers) — but
the same CloudTrail event's `userIdentity.userName` showed the actual
subject GitHub had presented:

```
repo:mbgolden@11353267/fleetalert-ai@1374821891:ref:refs/heads/main
```

GitHub now embeds immutable numeric IDs (account ID, repository ID) into
the `sub` claim alongside the mutable names, specifically so that renaming
or deleting/recreating a repo or account can't be used to replay an old
trust relationship written for the old name. The trust policy's condition
was written for the plain `repo:OWNER/REPO:ref:...` format and never
matched the token GitHub actually issues now — hence a consistent, 100%
reproducible denial rather than an intermittent one.

The first fix attempted — dropping the `sub` condition entirely and relying
only on the separate, ID-stable `repository` and `ref` claims GitHub also
exposes — was rejected outright by IAM itself:

```
Failed to update trust policy. Trust policy with trusted principal
arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com
must evaluate, using StringEquals, StringLike or StringEqualsIgnoreCase,
token.actions.githubusercontent.com:sub or
token.actions.githubusercontent.com:job_workflow_ref which is not scoped
to all.
```

AWS hard-requires a scoped `sub` or `job_workflow_ref` condition for this
specific provider ARN — you cannot rely on `repository`/`ref` alone,
however tightly scoped they are.

## Decision
Keep the `sub` condition, but pattern-match around the immutable ID
segments with `StringLike` wildcards instead of matching the full string
exactly:

```json
"Condition": {
  "StringEquals": {
    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
  },
  "StringLike": {
    "token.actions.githubusercontent.com:sub": "repo:mbgolden@*/fleetalert-ai@*:ref:refs/heads/main"
  }
}
```

This satisfies AWS's "must be scoped, not `*`" requirement (the org name,
repo name, and branch are all literal) while tolerating whatever numeric
IDs GitHub inserts. Confirmed working: `terraform-plan` ran and succeeded
against this trust policy.

## Consequences
- Any future AWS OIDC role for a *different* repo/org needs the same
  `@*` wildcard treatment in its `sub` condition, not the plain
  `repo:OWNER/REPO:...` pattern most tutorials (and AWS's own older docs)
  still show — that pattern is now stale for accounts where GitHub has
  rolled out immutable-ID subjects.
- The generic, unhelpful CloudTrail `errorMessage` for denied
  `AssumeRoleWithWebIdentity` calls means diagnosing *any* future OIDC
  trust issue here should start from `userIdentity.userName` in the
  CloudTrail event record, not the error message.
