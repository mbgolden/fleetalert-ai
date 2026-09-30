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
