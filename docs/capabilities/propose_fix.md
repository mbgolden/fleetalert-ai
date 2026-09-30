# propose_fix

The model's way of finishing an investigation. It records a proposal and
**executes nothing.**

| | |
|---|---|
| Safety tier | `proposes_action` |
| Idempotent | yes (recording only) |
| Model can call it | yes |
| Owner | FleetAlert agents platform |

**Input:**
`{ "fix_id": non-empty string, "description": non-blank string, "confidence": number 0-1 }`.
All three fields are required, and no others are allowed.

**Output:** `{ "received": true, "fix_id": string }`

**What happens after a successful call.** The agent loop, not this
capability, decides whether the proposal can go further. Each check is
recorded as a decision span:
1. **The fix_id must not have been rejected already** this alert
   (`guardrail.not_previously_rejected`). If it was, the alert routes to
   support.
2. **The fix_id must be on the whitelist** (`guardrail.whitelist`). If it
   isn't, the alert routes to support.
3. **`request_confirmation` runs**, and the alert waits for a human.

**Guarantees**
- **A schema-valid call can't run anything.** The most it can do is start a
  wait for human confirmation.

**Known failure modes**
- **Missing fields.** Claude has sent `propose_fix` without `fix_id`, and
  separately with only `fix_id`. Once that crashed the run, and once it left
  a half-empty proposal in the UI. The schema now rejects both, and the model
  gets a tool error naming the missing fields.
- **Cut off at the output limit.** A recorded eval run hit max_tokens partway through this call, so it arrived with only . The model then resent it twice without , which came after the long description in the schema, and finally sent a placeholder rationale. Now the loop never runs a tool call from a  response (it records  and asks for a retry), the output ceiling is 4096,  comes before , and the description asks for 2-5 sentences.
- **A non-whitelisted fix_id is not an error.** It is a legitimate "I'd
  escalate this" answer, and it routes to human support.
