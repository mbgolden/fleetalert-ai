// Eval data for the Evals page, read at build time from the backend's eval
// harness (backend/evals, ADR-0012). No API: the results are versioned files
// in the repo, and a new recorded run redeploys the site.

import scenarioDefs from "../../../backend/evals/scenarios.json";

export interface Grade {
  name: string;
  passed: boolean;
  gating: boolean;
  detail: string;
}

export interface Proposal {
  round: number;
  fix_id: string;
  confidence: number | null;
  description: string | null;
}

export interface Trial {
  passed: boolean;
  stale: boolean;
  outcomes: string[];
  error: string | null;
  cost_usd: number;
  model_calls: number;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  grades: Grade[];
  proposals: Proposal[];
}

export interface ScenarioResult {
  alert_id: string;
  pass_rate: number;
  trials: Trial[];
}

export interface EvalRun {
  tier: string;
  model: string;
  started_at: string;
  overall_pass_rate: number;
  total_cost_usd: number;
  gate: { min_scenario_pass_rate: number; min_overall_pass_rate: number; failures: string[] };
  scenarios: Record<string, ScenarioResult>;
}

export interface ScenarioDef {
  scenario_id: string;
  alert_id: string;
  summary: string;
  why: string;
  entry_point: string;
  rounds: { acceptable: string[]; reject_with: string | null }[];
  requires_conflict_note: boolean;
  max_confidence: number | null;
  max_cost_usd_per_round: number;
}

export const SCENARIOS: ScenarioDef[] = scenarioDefs;

// Each recorded run is its own lazily loaded chunk.
const runLoaders = import.meta.glob<EvalRun>("../../../backend/evals/results/*.json", {
  import: "default",
});

export interface RunRef {
  id: string; // e.g. "2026-09-30T1926-claude-sonnet-5"
  load: () => Promise<EvalRun>;
}

export const RUNS: RunRef[] = Object.entries(runLoaders)
  .map(([path, load]) => ({ id: path.split("/").pop()!.replace(/\.json$/, ""), load }))
  .sort((a, b) => b.id.localeCompare(a.id)); // newest first

// What changed before each recorded run, so the history reads as a story.
export const RUN_NOTES: Record<string, string> = {
  "2026-09-30T1238":
    "First recorded run. Passed its gate at 94%, but one proposal's entire rationale was “Test”. The recording traced it to responses cut off at max_tokens.",
  "2026-09-30T1251":
    "After the truncation fix: never run a cut-off tool call, shorter rationales, confidence before description.",
  "2026-09-30T1926":
    "After the prompt change to resolve KB conflicts from telemetry, with the email scenario added.",
};

export interface Finding {
  title: string;
  found: string;
  cause: string;
  fix: string;
  adr: string;
}

const ADR_BASE = "https://github.com/mbgolden/fleetalert-ai/blob/main/docs/decisions/";

// Real problems the evals (and one live trace) surfaced, in order.
export const FINDINGS: Finding[] = [
  {
    title: "A scenario whose evidence contradicted its own answer",
    found: "First live run: cabin-drift failed 0/3, with the model proposing a service visit every time.",
    cause:
      "The seeded telemetry showed a refrigeration fault, and the KB entry never explained why a remote reset would help. The model was right; the expected answer wasn't supported.",
    fix: "Fixed the data, not the grader: the telemetry now carries the controller's own reading, so the KB-003 signature is visible.",
    adr: `${ADR_BASE}ADR-0012-eval-harness.md`,
  },
  {
    title: "A proposal whose whole rationale was “Test”",
    found: "First recorded run: 94% pass, but reading the recordings showed one trial's rationale was a placeholder.",
    cause:
      "A response hit max_tokens partway through propose_fix. The loop ran the truncated call, and three validation errors later the model filled the field with “Test”.",
    fix: "The loop never runs tool calls from a cut-off response, confidence now comes before the long description, and a new grader requires a rationale that cites evidence. The next run was 27% cheaper, with zero tool errors.",
    adr: `${ADR_BASE}ADR-0012-eval-harness.md`,
  },
  {
    title: "A prompt that told the model to ignore its own evidence",
    found: "The first live email investigation proposed a service visit even though its rationale said the telemetry matched a sensor glitch.",
    cause: "The system prompt said to “prefer the more cautious option” whenever KB entries disagree, and the email's safety tone added weight.",
    fix: "Caution is now only a tie-breaker when evidence can't decide. Measured: 21/21 trials passed, and the email scenario chose the sensor restart 3/3.",
    adr: `${ADR_BASE}ADR-0016-simulated-email-entry-point.md`,
  },
];

export function runStamp(id: string): string {
  return id.slice(0, 15);
}

export function runModel(id: string): string {
  return id.slice(16);
}

export function formatRunTime(id: string): string {
  // "2026-09-30T1926" -> "2026-09-30 19:26 UTC"
  const stamp = runStamp(id);
  return `${stamp.slice(0, 10)} ${stamp.slice(11, 13)}:${stamp.slice(13, 15)} UTC`;
}
