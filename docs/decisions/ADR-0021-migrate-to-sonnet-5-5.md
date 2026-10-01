# ADR-0021: Migrate the agent from Sonnet 5 to Sonnet 5.5, on eval evidence

## Status
Accepted (2026-10-01).

## Context
The agent ran on `claude-sonnet-5`. Sonnet 5.5 has the same price per
token. Both the eval harness (ADR-0012) and the original plan said a model
change ships on measured results, not on a version number: a newer model
can be better overall and still worse at the specific judgment calls this
agent is graded on. Those calls are resolving a KB conflict from telemetry,
holding the line after a rejection, ignoring instructions in an email, and
staying modest when no KB entry fits.

## Evidence
Same 8 golden scenarios, same graders, 3 trials each, against real models.
Sonnet 5 had two recorded runs (2026-10-01 00:11 and 01:46). Sonnet 5.5 had
one (02:16).

| | Sonnet 5 (00:11) | Sonnet 5 (01:46) | **Sonnet 5.5 (02:16)** |
|---|---|---|---|
| Trials passed | 24/24 | 24/24 | **24/24** |
| Total cost | $0.698 | $0.676 | **$0.437** (−36%) |
| Mean latency per trial | 13.0 s | 13.8 s | **5.8 s** (−56%) |
| Mean output tokens per trial | 1,264 | 1,278 | **605** (−52%) |
| Mean input tokens per trial | 8,217 | 7,686 | **6,076** |
| Calibration warnings (`compressor-no-kb`) | 2 of 3 | 2 of 3 | **0 of 3** (0.55-0.60) |

Scenario by scenario:
- **Same outcome in all 24 trials as Sonnet 5.**
- **Cheaper and faster in every scenario.** The biggest gains were where
  Sonnet 5 had wandered: `compressor-no-kb` fell from 3.7-4.3 model calls to
  3.0, and from $0.050 to $0.023.
- **Rationales were shorter but no less grounded.** In a sample of first
  trials they ran about 480-810 characters, against 640-1,220 for Sonnet 5. They still name both KB entries, the deciding
  readings, and what rules the other entry out. In the email scenario, every
  5.5 rationale says outright that the email's request to skip approval is
  ignored.
- **Confidence moved in the right directions.** It's higher where the
  evidence is unambiguous (sensor glitch 0.88-0.90, leak 0.90-0.92). It's
  lower where it isn't: 0.55-0.60 with no KB entry, and 0.4-0.5 after a
  rejection.

The sample is one run against two, because one run costs real money. The
differences are large and point the same way in every scenario, so they
aren't trial-to-trial noise. The weekly scheduled run keeps watching.

## Decision
- **Deploy `claude-sonnet-5-5`.** It's the `FLEETALERT_MODEL` setting on
  the agent-loop Lambda and the config default, so evals and production
  agree on the model.
- **Make the 5.5 run the baseline.** Its recordings are the replay tier's
  cassettes.
- **Handle `stop_reason: "refusal"`.** This was the one item on the Sonnet
  5.5 migration checklist that applied to this loop. The other required
  items didn't apply: no disabled thinking, no forced `tool_choice`, the
  message history is already append-only with blocks passed back
  unchanged, and there's no computer use or advisor tool. A refusal now
  routes to support (`model_refused`) instead of being nudged up to six
  times.
- **Leave effort at the default.** The evals pass at the default with
  better cost and latency, so tuning it is a later experiment, measured the
  same way.

## Consequences
- An investigation now typically costs about $0.014-0.036 and takes about
  4-12 s, down from $0.018-0.057 and 9-28 s. The $1.25 daily cap (ADR-0017)
  buys more investigations.
- The `compressor-no-kb` calibration warning cleared on 5.5. The backlog
  item to split confidence into diagnosis and action stays open. It's a
  better contract either way, but it's no longer urgent.
- Rolling back is a one-line change of the same setting, re-measured with
  the same eval run.
- The Evals workflow's model input became a dropdown during this
  comparison. The first "5.5" run had silently re-run the default model
  because the free-text box was blank, which caught a usability gap in the
  eval tooling itself.
