# ADR-0014: A rejected fix triggers one knowledge-base-backed re-investigation

## Status
Accepted. Built before the Capabilities Engine and written up after the fact on 2026-09-30.

## Context
Originally, Reject was an end state. A human saying "not that fix" stopped
the investigation, even when the knowledge base (the RAG step) had another
plausible answer. A human rejection is the most valuable signal the agent
gets, and throwing it away made the human the fallback for every
disagreement. An unbounded retry loop has the opposite problem: a visitor
could bounce proposals back and forth, spending API budget, and the agent
could eventually wander off the whitelist.

## Decision
- **Rejection re-enters the investigation.** `reject_fix` records the
  rejected `fix_id` and reason on the alert and sets the status back to
  `investigating`. The API calls `SendTaskFailure` with error
  `RetryWithNewFix`, and the state machine's Catch loops
  `WaitForConfirmation` back to `RunInvestigation`.
- **The Catch uses `ResultPath: null`.** The default (`$`) replaces the
  whole state input with the error and loses `alert_id`. The first version
  failed that way: the handler threw `KeyError` on `event["alert_id"]`.
- **The next round is told what was rejected.** Its opening message names
  each rejected `fix_id` and the human's reason, and asks for a different
  angle from the knowledge base, or an honest escalation if nothing fits.
- **A guardrail backs up the prompt.** `guardrail.not_previously_rejected`
  routes to support if a rejected `fix_id` is proposed again. The eval
  harness measures whether the model needed it (the "respected rejection"
  grader, ADR-0012).
- **One retry, no more.** `MAX_REJECTION_ROUNDS = 1` means at most two
  proposals per alert. A second rejection routes straight to support
  without another model call.

## Consequences
- The demo shows the agent using feedback, not just asking for approval.
  `oil-pressure-rejected` in the eval suite checks that it still says "no
  remote fix exists" under pressure.
- Each extra round is a full investigation, bounded by the cap. In the
  recorded eval runs, the two-round scenario costs about $0.06 in total,
  against about $0.02 for a single round.
- Every round is its own trace, linked by `previous_trace_id`, so the trace
  viewer shows "Round 2, after rejection" as a separate card.
