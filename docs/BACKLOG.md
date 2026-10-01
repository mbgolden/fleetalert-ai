# Backlog

Known follow-ups, each with the evidence that raised it. When an item is
done, remove it and point to the commit or ADR in the PR.

## Split confidence into diagnosis and action
Raised 2026-09-30 by the eval harness (ADR-0012).

`compressor-no-kb` has no KB entry, so the calibration check expects
confidence of 0.7 or below. Sonnet 5 scored 0.75-0.82 in all three trials
of the 12:51 recorded run, even though the system prompt asks for 0.6 or
below. The rationales explain why: Claude is fairly sure a technician
should look at a faulted compressor (the action), and unsure of the root
cause (the diagnosis). One number can't hold both, so the check is
measuring the wrong thing.

Update, 2026-09-30 19:26 recorded run: after the KB-conflict prompt change
(ADR-0016), `compressor-no-kb` came in at 0.55-0.60 in all three trials,
and the warning cleared. The symptom is gone for now, but the conceptual
problem remains: the proposal UI still shows one "confidence" for two
different questions. Lower priority, still worth doing.

Update, 2026-10-01 00:11 recorded run: the warning came back in 2 of 3
`compressor-no-kb` trials. The prompt line moved the average without fixing
the underlying ambiguity, which is more evidence for the split.

- Replace `confidence` on `propose_fix` with `diagnosis_confidence` (how
  sure the root cause is right) and `action_confidence` (how sure this fix
  is the right next step).
- Calibration grader: without KB support, `diagnosis_confidence` ≤ 0.6.
  `action_confidence` can stay high.
- Show both in the UI's proposed-fix box and trace.
- Update `request_confirmation`, `docs/capabilities/propose_fix.md`, the
  tests and the evals, and re-record the cassettes.
- Consider doing this with the Sonnet 5.5 comparison run, so both models
  are measured on the new contract.
