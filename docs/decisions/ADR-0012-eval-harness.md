# ADR-0012: Eval harness with live and replay tiers

## Status
Accepted

## Context
Until now the agent's behaviour was checked by clicking through the demo.
Unit tests cover the loop, capabilities and guardrails, but only against
scripted model responses. They prove the code does the right thing with a
given answer, not that the model gives the right answer.

Three changes were coming that could quietly change answers: rewording the
system prompt (its "prefer the more cautious option" line may push the
sensor-glitch alert toward a needless service visit), migrating from Sonnet 5
to Sonnet 5.5, and adding new entry points. None of those should ship on
"it looked fine when I tried it once". A model is non-deterministic, so a
single run is an anecdote.

## Decision
A golden-scenario eval harness in `backend/evals/`, with two tiers.

**Scenarios** are one per seeded alert, plus a reject-and-retry case. Each
expectation comes from the seeded telemetry and knowledge base, with the
reasoning recorded next to it, so the expectation itself can be reviewed.

**Graders are deterministic and read the trace spans** the Capabilities
Engine already writes (ADR-0011). They check the outcome, that evidence was
gathered before proposing, that the KB conflict is acknowledged, that a
rejected fix isn't re-proposed, that no capability call was denied, and cost
per round. No LLM judge: each of these has an objectively right answer, so
a judge would only add cost and its own variance. Confidence calibration and
tool-input errors are reported but don't gate. Tests show each gating grader
failing on a trajectory built to trip it.

**Live tier.** Real Claude runs 3 trials per scenario. The gate is each
scenario passing at least 2/3 and 80% overall. Runs happen on PRs that touch
agent code, weekly to catch model drift, and on demand with a model override.
Each trial runs against a private in-memory DynamoDB (moto) seeded like the
demo: it's the production code path, but never the live site's data.

**Replay tier.** A passing live trial can be recorded as a cassette of the
model's responses. Replay runs the real loop against those responses in the
normal pytest suite: free, deterministic, on every PR. It catches code
changes that break a trajectory the real model produced, such as a renamed
tool, a tightened schema or a guardrail regression. Each cassette
fingerprints the prompt, tools and opening message. When those change, the
cassette is reported stale and skipped rather than trusted, and the live
tier on that same PR is the signal.

Results are versioned. A recording run commits cassettes, a dated results
file and `baseline.json`, which later reports show deltas against.

## Consequences
- A prompt or model change now ships with a pass-rate number instead of an
  impression. The Sonnet 5.5 migration is a live run with a model override,
  compared against the Sonnet 5 baseline.
- A live run costs about $0.60 (18 investigations, one of them two rounds).
  With the path filter and a weekly schedule, that's a few dollars a month,
  paid with a separate API key so eval spend is visible on its own.
- The live gate is advisory on PRs: it isn't a required check, because
  path-filtered workflows can't be required without blocking unrelated PRs.
  A red run is still visible on the PR.
- Deterministic graders can't judge prose quality, such as whether a
  rationale is well argued. If that matters later, an LLM judge can be added
  as a non-gating grade and calibrated against human labels first.
- Six scenarios is a small set. It covers every seeded path plus
  rejection, but new entry points (email, autonomous) should add their own
  scenarios as they land.

## First live run (2026-09-30, Sonnet 5, 3 trials)
Overall pass rate was 83%. The gate failed on one scenario, and the failure
was in the test data, not the model.

- **`cabin-drift`: 0/3.** Every trial proposed `schedule_service_visit`
  instead of the expected `send_diagnostic_reset`. The seeded telemetry had
  the cabin warming from 2.0 to 7.6 C and still climbing while the
  compressor drew full current, which is what a failing refrigeration
  circuit looks like. KB-003 said only "cabin temperature slowly drifting",
  with nothing to explain why a remote reset would fix it. Sending a
  technician was the reasonable call, so the expectation was wrong, not the
  answer. Loosening the grader to accept a service visit would have hidden
  the real problem: a demo scenario whose evidence doesn't support its own
  answer. The fix was to the data. The telemetry now carries the
  controller's own reading, which stays at setpoint while the cabin probe
  runs warm and the compressor eases off: a controller calibration drift.
  KB-003 now describes that signature and when it does *not* apply. A seed
  test pins the story.
- **`compressor-no-kb`: passed, but overconfident.** All three runs scored
  confidence above 0.7 with no KB entry behind the fix (a non-gating
  warning). The system prompt now asks for 0.6 or below, stated in the
  description, when no KB entry matches. Both changes are measured by the
  next run.
- `sensor-glitch` passed 3/3, so the prompt's "prefer the more cautious
  option" line isn't biasing the ambiguous case the way it was feared to.
- The failed-trial section of the report now includes the model's own
  rationale, so a miss can be triaged from the job summary alone.

The follow-up run passed every scenario 3/3, which confirmed both changes.
cabin-drift proposed the reset every time, and compressor-no-kb was
overconfident in one trial of three, down from three.

## First recorded run (2026-09-30 12:38, Sonnet 5)
The run passed its gate at 94%, but reading the recordings turned up a real
bug that the pass rate alone would have hidden.

- **`sensor-glitch` #3 proposed the right fix with the rationale "Test".**
  The only reason it failed was that the conflict grader found no mention
  of KB-001/KB-002. In another scenario, that proposal would have passed.
- **The cause was output truncation.** The recording of trial #1 shows the
  second response stopped at `max_tokens` (2048). The `propose_fix` call was
  cut off and arrived with only `fix_id`. The loop never checked
  `stop_reason`, so it ran the truncated call and returned a validation
  error. The model then resent it twice without `confidence`, which came
  after the long description in the schema, before getting it right. Trial
  #3 went the same way, and its last attempt filled the field with "Test".
- **Fixes:**
  - The loop never runs tool calls from a `max_tokens` response. It
    records a `guardrail.truncated_output` span and tells the model to
    retry.
  - The output ceiling is now 4096 tokens. That's a ceiling, not a cost.
  - `confidence` now comes before `description` in the schema, and the
    description asks for 2-5 sentences.
  - A new gating grader requires every rationale to be at least 60
    characters and cite a KB entry or a reading.
  - Truncations count toward the reported tool-error warning.
- These changes alter the prompt and tools, so the replay tier now reports
  all six cassettes as stale and skips them. That is its designed behaviour.
  They are re-recorded by the next live run.
