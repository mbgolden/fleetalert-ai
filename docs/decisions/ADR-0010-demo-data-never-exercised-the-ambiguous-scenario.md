# ADR-0010: The demo data never exercised the ambiguous scenario

## Status
Accepted

## Context
The brief asks for one deliberately ambiguous scenario to stress the agent.
The seed data has one: KB-001 (sensor glitch -> `restart_sensor`) and
KB-002 (genuine coolant loss -> `schedule_service_visit`) share the same
machine type and issue pattern, "coolant temp spike". The design assumed the
agent would retrieve both, notice they disagree, and resolve the conflict
from evidence.

While planning the evaluation harness, a live investigation of ALERT-1001
showed it never had the chance. Claude's own `propose_fix` rationale said:

> telemetry snapshots (both 60-min and 180-min windows) returned no readings,
> and knowledge base searches for "coolant temperature spike,"
> "coolant_temp_spike," "engine overheating," and "coolant sensor faulty
> reading" all returned zero matches.

Two independent bugs, both in the demo's data layer rather than the agent:

1. **No telemetry was ever seeded.** `put_telemetry_reading` existed and was
   unit-tested, but nothing called it outside tests. Every investigation saw
   an empty window.
2. **Knowledge-base search was exact substring matching.** The query
   "coolant temperature spike" is not a substring of "coolant temp spike" (and
   vice versa), so neither conflicting entry was ever returned. The unit test
   passed because it searched with the exact stored phrase.

With no evidence and no KB hits, the agent fell back to the cautious answer
(`schedule_service_visit`, confidence 0.35). That's a reasonable choice, but
it means the ambiguous scenario, the thing the demo exists to show, had never
actually run.

An eval harness built on top of this would have held the agent to a standard
against empty data. It would have looked green while testing nothing.

## Decision
- **Deterministic seeded telemetry per alert** (`seed_data.seed_telemetry`):
  readings every 10 minutes for 3 hours either side of each alert, no
  randomness. Each alert's readings tell a specific story:
  - ALERT-1001: coolant temperature climbs while coolant level falls (a real
    leak, so KB-002).
  - ALERT-1004: one reading spikes and immediately returns, with level flat (a
    sensor glitch, so KB-001).
  - ALERT-1002: cabin temperature drifts off setpoint while the compressor
    runs normally (KB-003).
  - ALERT-1003: oil pressure declines steadily at constant rpm (KB-004).
  - ALERT-1005: the compressor current spikes, then faults out (no KB entry,
    so route to support).
- **Alerts on the same machine are at least 6 hours apart** (ALERT-1004 and
  ALERT-1005 moved to the previous day), so the maximum 180-minute window
  never mixes two alerts' evidence.
- **Word-overlap KB matching** with a small explicit synonym table
  (temperature -> temp, drifting -> drift, ...), stopwords, and a crude plural
  strip. A match needs the whole pattern, two pattern words, or one pattern
  word plus a distinct description word. A single shared word is never
  enough, which a test caught when "temp" pulled a refrigeration entry into a
  coolant query.
- **Tests pin the behavior with the phrasings Claude actually used live**,
  not the stored phrase.

## Alternatives considered
- **Embeddings or a vector store.** For four KB entries it adds cost, a new
  service, and nondeterminism the eval harness would have to absorb.
  Revisit if the KB grows past what a synonym table can cover.
- **Telling the model the exact KB phrasing in the prompt.** That would have
  hidden the retrieval bug instead of fixing it.

## Consequences
- The same KB conflict now resolves to different, evidence-backed answers on
  ALERT-1001 and ALERT-1004. That gives the eval harness golden outcomes worth
  holding the agent to.
- Seeded telemetry is part of the Reset Alerts path, so the Lambda gained
  `dynamodb:BatchWriteItem`.
- Lesson recorded for the harness: a scenario only counts as covered if a
  test asserts the agent actually *saw* the evidence, not just that it
  produced an answer.
