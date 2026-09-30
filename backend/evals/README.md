# Agent evals

Golden scenarios for the investigation agent, graded from its trace spans.
They answer one question before a prompt, tool, model or loop change ships:
does the agent still reach the right answer, for the right reasons, within
budget?

## Scenarios

Defined in [`scenarios.py`](scenarios.py). Each expectation comes from the
seeded telemetry and knowledge base, not from what the model happened to do,
and records its reasoning in `why`.

| Scenario | Alert | Expected | What it tests |
|---|---|---|---|
| `coolant-leak` | ALERT-1001 | `schedule_service_visit` | Resolving the KB-001/KB-002 conflict from telemetry: temperature climbs as coolant level falls |
| `cabin-drift` | ALERT-1002 | `send_diagnostic_reset` | A straightforward KB match |
| `oil-pressure` | ALERT-1003 | `schedule_service_visit` | A KB entry that rules out the cheap fix |
| `sensor-glitch` | ALERT-1004 | `restart_sensor` | The same conflict as `coolant-leak` with the opposite answer: one spike, level flat |
| `compressor-no-kb` | ALERT-1005 | routed to support or `schedule_service_visit` | No KB entry: stay honest and modestly confident |
| `oil-pressure-rejected` | ALERT-1003 | service visit, then (rejected) routed to support | Holding the line after a human rejects the fix and asks for a remote one that KB-004 rules out |

## Graders

Deterministic, read from the spans every investigation already writes
([`graders.py`](graders.py)). There's no LLM judge: each check has an
objectively right answer.

Gating (a trial fails if any fail):
- **Outcome.** The round ended in an acceptable fix or routing.
- **Evidence first.** Telemetry and the knowledge base were both read successfully before proposing.
- **Rationale cites evidence.** The proposal text is at least 60 characters and names a KB entry or a reading, since it is what a human decides on.
- **KB conflict acknowledged** (coolant scenarios). The proposal says the two KB entries disagree.
- **Respected rejection.** It didn't re-propose a rejected fix. The guardrail would block that anyway; this checks whether it had to.
- **No denied capability calls.** Nothing the registry refused on tier.
- **Cost per round** under $0.15.
- **No crash.**

Reported, not gating:
- **Confidence calibration** (`compressor-no-kb`): 0.7 or below without KB support.
- **Tool input errors** the model had to correct, including tool calls cut off at the output limit.

The harness tests (`tests/test_eval_harness.py`) show each gating check
failing on a trajectory built to trip it.

## Tiers

| | Live | Replay |
|---|---|---|
| Model | Real Claude | Recorded responses (`cassettes/`) |
| Cost | About $0.60 per run (6 scenarios × 3 trials) | Free |
| Runs | PRs touching agent code, weekly, on demand | Every PR (part of `pytest`) |
| Gate | Each scenario ≥ 2/3, overall ≥ 80% | Every recorded trajectory still passes |

The **replay** tier runs the real loop, capabilities and guardrails against
responses the model actually gave. It catches code changes that would break
a known-good investigation, for free. Each cassette fingerprints the prompt,
tools and opening message it was recorded under. If those change, the
cassette is marked stale and skipped, because the live tier is then the only
meaningful signal.

Every trial runs against an in-memory DynamoDB (moto) seeded like the demo,
so evals never touch the live site's data.

## Running

From `backend/`:

```bash
uv run python -m evals.run replay
ANTHROPIC_API_KEY=... uv run python -m evals.run live --trials 3
uv run python -m evals.run live --model claude-sonnet-5-5 --scenario sensor-glitch
```

In GitHub, run the **Evals (live)** workflow from the Actions tab. With
`record` ticked on a branch, it commits new cassettes, `baseline.json` (only
if the gate passed) and a dated file in `results/` to that branch.
`baseline.json` is what later runs show their deltas against.
