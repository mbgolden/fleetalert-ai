# search_knowledge_base

Retrieval over known issue patterns for the alert's machine type. This is
the "R" in the agent's RAG: the model calls it mid-loop, and the matches go
straight back into its reasoning.

| | |
|---|---|
| Safety tier | `read_only` |
| Idempotent | yes (retried once on failure) |
| Model can call it | yes |
| Owner | FleetAlert agents platform |

**Input:** `{ "symptom_description": non-empty string }`

**Output:** `{ "matches": [ { kb_id, machine_type, issue_pattern, description, known_fix } ] }`,
best match first.

**Guarantees**
- **Scoped to the machine type** from the investigation context.
- **Matching is deterministic word overlap** with a small synonym table: a
  match needs the whole issue pattern, two pattern words, or one pattern word
  plus a description word. A single shared word is never enough (ADR-0010).
- **Conflicting entries are returned together** on purpose. KB-001 (sensor
  glitch) and KB-002 (coolant leak) share a pattern, and it is the agent's
  job to resolve the conflict from telemetry, not the search's job to hide
  it.

**Known failure modes**
- **Vocabulary gaps.** A phrasing with no overlap returns `[]`. The agent
  should try another phrasing or say the KB has no coverage (ALERT-1005's
  compressor fault deliberately has none).
- **Exact substring matching**, the original implementation, returned
  nothing for "coolant temperature spike" against "coolant temp spike", so
  the ambiguous scenario never ran. Tests now pin the phrasings Claude
  actually used.
