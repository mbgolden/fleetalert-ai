# Backlog

Known follow-ups, each with the evidence that raised it. When an item is
done, remove it and point to the commit or ADR in the PR.

## Parked

Items that were investigated and deliberately not built. Each one names the
evidence that would bring it back.

### Split confidence into diagnosis and action
Raised 2026-09-30 by the eval harness (ADR-0012). Parked 2026-10-01.

**The problem.** `compressor-no-kb` has no KB entry, so the calibration
check expects confidence of 0.7 or below. On Sonnet 5 it scored above that
in most trials (0.75-0.82), across three recorded runs. A prompt line moved
the average but didn't hold. The rationales explained why: Claude was fairly
sure a technician should look at a faulted compressor (the action), and
unsure of the root cause (the diagnosis). One number was holding two
answers.

**Why it's parked.** On Sonnet 5.5, the deployed model since ADR-0021, the
warning didn't fire: 0.55-0.60 in all three trials, with rationales that
say outright that no KB entry documents the fix. The split would change a
capability contract, the confirmation flow, the UI and every recording, to
fix a symptom the current model doesn't show. That's real cost and risk
with no measured benefit.

**What would bring it back:**
- The weekly live eval shows the `compressor-no-kb` calibration warning in
  2 or more trials of a run.
- A model change brings it back.
- A real user of the proposal box needs to tell "is this the right
  diagnosis" apart from "is this the right next step".

**The design, if it comes back.** Replace `confidence` on `propose_fix` with
`diagnosis_confidence` and `action_confidence`. Grade calibration on
`diagnosis_confidence` (0.6 or below without KB support), and show both in
the proposal box and the trace. Update `request_confirmation`, the contract
doc, the tests and the evals, then re-record.
