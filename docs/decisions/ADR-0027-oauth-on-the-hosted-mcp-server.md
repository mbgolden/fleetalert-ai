# ADR-0027: Turn on OAuth for the hosted MCP server, so Claude Desktop can connect

## Status
Accepted (2026-10-25). Takes fleetalert-mcp v0.3.0 (its ADR-0006 and ADR-0007).

## Context
ADR-0025 put the MCP server in this account behind API Gateway with static
bearer tokens. Claude Code sends a header; Claude Desktop and claude.ai do
not. They follow the MCP authorization spec: discover an authorization
server from the protected-resource metadata, register, send the person
through `/authorize` with PKCE, exchange a code at `/token`. The hosted
server was therefore unreachable from the Claude most visitors have.

fleetalert-mcp v0.3.0 makes the server its own OAuth 2.1 authorization
server without any store: client registration, authorization request, code
and tokens are each sealed (AES-GCM) under a key derived from the
`state_key` the secret already holds. Its consent page signs a connector in
as the read-only `visitor`, or as an operator's tier if they paste their
governor key.

## Decision
- **Bump `FLEETALERT_MCP_REF` to `v0.3.0`** and set
  `FLEETALERT_MCP_OAUTH_ENABLED=true` on the function. Nothing else changes:
  no new secret, no table, no new API. The same gateway now also serves
  `/authorize`, `/token`, `/register`, `/revoke`, `/consent` and the
  authorization-server metadata.
- **The public posture is unchanged.** An OAuth grant with nothing entered
  is the `visitor` principal at `read_only`, the same tier as the published
  visitor token, under the same rate limits and the same daily cost guard.
  Only a governor key, which the operator holds, raises a connector above
  that.
- **MCP-started rounds are tagged** `mcp` (ADR-0026) because v0.3.0 sends
  the entry-point header, so a visitor who connects their Claude Desktop and
  starts an investigation sees it arrive in the Activity feed as its own way
  in.

## Consequences
- Claude Desktop and claude.ai can add the demo as a custom connector with
  just its URL. The README says how.
- Authorization codes are not single-use and refresh tokens cannot be
  revoked early, because there is no store; both are bounded by short
  lifetimes and by the code being tied to the registering client's PKCE
  verifier. fleetalert-mcp's backlog holds the DynamoDB nonce table if the
  demo ever needs it.
- The first real Claude Desktop connection is the acceptance test; the
  SDK's own OAuth client has exercised the flow through a Lambda shim.
