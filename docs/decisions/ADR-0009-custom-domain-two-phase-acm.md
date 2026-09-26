# ADR-0009: Custom frontend domain via a two-phase ACM apply

## Status
Accepted

## Context
The demo is served from a `*.cloudfront.net` URL. The portfolio site
(`10finger.dev`) links to it, and a visitor landing on an unrelated domain
is a rough hand-off. The frontend is a root-relative SPA, so a subdomain
(`fleetalert.10finger.dev`) needs no frontend code changes; a path slug
would (Vite `base`, router `basename`, plus a proxy layer).

A CloudFront alias needs an ACM certificate (in us-east-1) that has been
DNS-validated. Validation needs a CNAME in the 10finger.dev zone, which
lives outside this Terraform, so Terraform cannot finish the job alone.

## Decision
Two variables in `infra/envs/demo`:

- `frontend_custom_domain` -- requests the ACM cert and allows the origin
  in the API's CORS list. Apply #1 outputs `acm_validation_records`.
- `frontend_attach_custom_domain` -- adds `aws_acm_certificate_validation`
  and the CloudFront alias/certificate. Flipped to `true` only after the
  validation CNAME is in DNS.

Then a final CNAME `fleetalert -> frontend_cname_target` points the
subdomain at CloudFront.

## Why
`aws_acm_certificate_validation` blocks until validation succeeds (up to
45 minutes). Putting it in the first apply would hang on a record nobody
has created yet. Splitting the apply keeps each run short and failure
modes obvious.

## Consequences
- One extra manual apply and two DNS records, once.
- Default `*.cloudfront.net` URL keeps working, so the old link and CORS
  entry are not broken by the switch.
- The apply role needs `acm:*Certificate*` permissions; the plan role
  needs ACM read.
