# ADR-0007: Defer CORS configuration until final domains are known

## Status
Accepted

## Context
The frontend (S3 + CloudFront) and the API (API Gateway HTTP API,
`*.execute-api.us-east-1.amazonaws.com`) are, and always will be, different
origins. Without CORS configured on the HTTP API, the browser will block
every request the frontend makes to it -- the `GET` routes included, and the
`POST` routes' preflight `OPTIONS` requests will fail outright. This is not
optional or deferrable once the frontend is actually pointed at a real API:
`infra/modules/api_gateway` currently has no `cors_configuration` block at
all, so the app will not work end to end without it.

What's genuinely undecided is *which* origin(s) to allow. Candidates depend
on decisions not yet made:
- The CloudFront distribution's default domain (`*.cloudfront.net`), which
  isn't known until that module is written and applied.
- A custom domain, if one gets attached to CloudFront (e.g. a subdomain of
  10finger.dev, matching PlayIt's convention) -- not yet decided for this
  project.
- Whether local development (`http://localhost:5173`) should also be
  allowed, and if so, only in a way that can't leak into the real deployed
  config.

## Decision
Document the requirement and the shape of the fix now; implement it once
the frontend's real domain (CloudFront default or custom) is known --
likely alongside building the still-not-built S3 + CloudFront module.

The fix, when applied, is an `aws_apigatewayv2_cors_configuration` block
(or the equivalent `cors_configuration` argument) on
`aws_apigatewayv2_api.this` in `infra/modules/api_gateway/main.tf`:

```hcl
resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
  tags          = var.tags

  cors_configuration {
    allow_origins = var.allowed_origins  # e.g. [module.frontend.distribution_domain]
    allow_methods = ["GET", "POST"]
    allow_headers = ["content-type"]
  }
}
```

`allowed_origins` becomes a variable threaded in from `infra/envs/demo`
once the frontend module exists and its domain is a Terraform output.

## Consequences
- The demo frontend cannot successfully call the API until this is done --
  don't treat the API Gateway + Lambda layer as "finished" independent of
  the frontend module; they're finished together.
- Scoping `allow_origins` to the real CloudFront/custom domain (rather than
  `*`) is the plan -- a wildcard would work for a demo but is worth avoiding
  even here, since it costs nothing to get right once the domain exists.
- Local dev against the real deployed API (rather than a mock) will need
  its own origin added deliberately, not as an accidental side effect of a
  wildcard.
