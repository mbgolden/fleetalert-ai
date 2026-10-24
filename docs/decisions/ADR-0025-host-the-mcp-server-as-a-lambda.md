# ADR-0025: Host the MCP server as a Lambda in the demo environment

## Status
Accepted (2026-10-24)

## Context
[fleetalert-mcp](https://github.com/mbgolden/fleetalert-mcp) exposes this
demo's API to Claude Code, Claude Desktop and other MCP clients, with the
same safety tiers the Capabilities Engine enforces (ADR-0011) and human
approval through MCP elicitation before a fix is confirmed. Until now it ran
only on the author's machine, so nothing on fleetalert.10finger.dev could
show it. A visitor should be able to connect their own Claude to the demo.

Options: the home box behind a Cloudflare tunnel (free, but down when the
box is), an always-on container on another platform (a second platform to
run, explain and pay for), or a Lambda in this account.

## Decision
- **A Lambda behind its own HTTP API**, `fleetalert-ai-demo-mcp`, deployed
  by this repo's Terraform and gated apply workflow (ADR-0005/ADR-0013).
  It costs nothing idle, is always on, and lands in the same decision log
  as the API it fronts. Its own API rather than routes on the demo API
  because the MCP server owns every path under its origin (`/mcp`, the
  OAuth protected-resource metadata, `/healthz`, `/metrics`) and needs no
  CORS; MCP clients are not browsers.
- **The code is pinned by git tag, not vendored.** A build script installs
  `fleetalert-mcp` from GitHub at `FLEETALERT_MCP_REF` (today `v0.2.0`)
  into `backend/build/mcp_package`, which the Lambda module zips, exactly
  like the backend package. Bumping the tag is how the demo takes a new
  server release; the two repos stay separately versioned.
- **Stateless JSON mode** (fleetalert-mcp ADR-0005): protocol 2026-07-28
  is one POST per request, so no sessions or SSE are needed and a Lambda
  fits. The elicitation state `confirm_fix` carries between two requests is
  sealed with a key every instance shares.
- **Tokens and that key live in a Secrets Manager secret**,
  `fleetalert-ai-demo-mcp-tokens`, whose value is set by hand, never through
  Terraform or a repository, the same rule as the Anthropic key. The server
  runs at the `executes_action` tier; the published visitor token is
  `read_only`, so visitors see everything and change nothing; a private
  `executes_action` token is the author's.
- **No custom domain yet.** The API Gateway endpoint is the public URL;
  bearer auth's issuer and resource are derived from it. A custom domain
  would change one setting and need the ACM two-phase dance (ADR-0009).

## Consequences
- The demo gains a fourth way in, with its own entry: an MCP client can
  list alerts, read trace summaries, and (with the right token and a client
  that supports elicitation) start an investigation or confirm a fix.
  MCP-started rounds are not yet labelled as such in the Activity feed; a
  `mcp` entry point is a follow-up in the backlog.
- Rate limits and `/metrics` counters are per Lambda container. The demo's
  daily cost guard (ADR-0017) remains the backstop against a visitor
  spending the budget; the MCP server's own limits bound one chatty client
  per container.
- Another Lambda, API, secret and IAM role under the `fleetalert-ai-demo-*`
  prefix the apply role is scoped to. Expect the usual round or two of
  undocumented read permissions on the plan role for the new resource
  types (the pattern recorded in project notes since ADR-0004).
- Before the first apply is useful, Michael sets the secret's value and
  the README's "connect your Claude" section needs the real endpoint and
  visitor token, which only exist after apply.
