import { useEffect, useState } from "react";

import {
  type EvalRun,
  FINDINGS,
  RUN_NOTES,
  RUNS,
  SCENARIOS,
  type ScenarioDef,
  type ScenarioResult,
  type Trial,
  formatRunTime,
  runModel,
  runStamp,
} from "../evals/data";

const REPO = "https://github.com/mbgolden/fleetalert-ai";

function pct(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

function usd(value: number, digits = 3): string {
  return `$${value.toFixed(digits)}`;
}

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)} s`;
}

function mean(trials: Trial[], pick: (t: Trial) => number): number {
  return trials.length ? trials.reduce((sum, t) => sum + pick(t), 0) / trials.length : 0;
}

function passedCount(run: EvalRun): [number, number] {
  const trials = Object.values(run.scenarios).flatMap((s) => s.trials);
  return [trials.filter((t) => t.passed).length, trials.length];
}

function outcomeLabel(outcomes: string[]): string {
  return outcomes.length ? outcomes.join(" → ").replaceAll("_", " ") : "no rounds";
}

function outcomeCounts(result: ScenarioResult): string {
  const counts = new Map<string, number>();
  for (const t of result.trials) {
    const key = outcomeLabel(t.outcomes);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts].map(([k, n]) => `${k} ×${n}`).join(", ");
}

function TrialCard({ trial, index }: { trial: Trial; index: number }) {
  const failing = trial.grades.filter((g) => g.gating && !g.passed);
  const warnings = trial.grades.filter((g) => !g.gating && !g.passed);
  return (
    <li className={`eval-trial ${trial.passed ? "passed" : "failed"}`}>
      <div className="eval-trial-head">
        <span className="eval-trial-status">{trial.passed ? "✓" : "✕"}</span>
        <span>Trial {index + 1}</span>
        <span className="eval-trial-outcome">{outcomeLabel(trial.outcomes)}</span>
        <span className="eval-trial-meta">
          {usd(trial.cost_usd, 4)} · {seconds(trial.latency_ms)} · {trial.model_calls} model calls
        </span>
      </div>
      {failing.map((g) => (
        <p key={g.name} className="eval-grade failing">
          ✕ {g.name}: {g.detail}
        </p>
      ))}
      {warnings.map((g) => (
        <p key={g.name} className="eval-grade warning">
          ⚠ {g.name}{g.detail ? `: ${g.detail}` : ""}
        </p>
      ))}
      {trial.error && <p className="eval-grade failing">✕ {trial.error}</p>}
      {trial.proposals.map((p) => (
        <blockquote key={p.round} className="eval-rationale">
          <strong>
            Round {p.round}: {p.fix_id}
            {p.confidence !== null && ` · ${Math.round(p.confidence * 100)}% confidence`}
          </strong>
          <span>{p.description}</span>
        </blockquote>
      ))}
    </li>
  );
}

function ScenarioRow({ def, result }: { def: ScenarioDef; result: ScenarioResult | undefined }) {
  if (!result) {
    return (
      <details className="eval-scenario">
        <summary>
          <span className="eval-scenario-id">{def.scenario_id}</span>
          <span className="eval-scenario-summary">{def.summary}</span>
          <span className="eval-pass none">not in this run</span>
        </summary>
      </details>
    );
  }
  const passed = result.trials.filter((t) => t.passed).length;
  const all = passed === result.trials.length;
  return (
    <details className="eval-scenario">
      <summary>
        <span className="eval-scenario-id">{def.scenario_id}</span>
        <span className="eval-scenario-summary">
          {def.summary}
          {def.entry_point !== "web" && (
            <span className={`entry-chip entry-${def.entry_point} card-chip`}>{def.entry_point}</span>
          )}
        </span>
        <span className={`eval-pass ${all ? "all" : passed === 0 ? "none" : "some"}`}>
          {passed}/{result.trials.length}
        </span>
        <span className="eval-scenario-meta">
          {usd(mean(result.trials, (t) => t.cost_usd), 4)} · {seconds(mean(result.trials, (t) => t.latency_ms))}
        </span>
      </summary>
      <div className="eval-scenario-body">
        <p>
          <strong>Expected:</strong>{" "}
          {def.rounds
            .map(
              (r, i) =>
                `${def.rounds.length > 1 ? `round ${i + 1}: ` : ""}${r.acceptable.join(" or ").replaceAll("_", " ")}` +
                (r.reject_with ? ` (then a human rejects it: “${r.reject_with}”)` : ""),
            )
            .join("; ")}
        </p>
        <p>
          <strong>Why:</strong> {def.why}
        </p>
        <p className="eval-outcomes">
          <strong>Outcomes:</strong> {outcomeCounts(result)}
        </p>
        <ol className="eval-trials">
          {result.trials.map((t, i) => (
            <TrialCard key={i} trial={t} index={i} />
          ))}
        </ol>
      </div>
    </details>
  );
}

export default function EvalsPage() {
  const [runs, setRuns] = useState<Map<string, EvalRun> | null>(null);
  const [selected, setSelected] = useState<string | null>(RUNS[0]?.id ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all(RUNS.map(async (r) => [r.id, await r.load()] as const))
      .then((loaded) => setRuns(new Map(loaded)))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const run = selected && runs ? runs.get(selected) : undefined;

  return (
    <div className="evals-page">
      <h1>Agent evals</h1>
      <p className="evals-intro">
        Every change to the agent's prompt, tools or model is measured against golden scenarios
        before it ships. Each scenario runs 3 times against real Claude, graded by deterministic
        checks read from the same trace spans the demo shows: the right outcome, evidence gathered
        before proposing, the knowledge-base conflict acknowledged, rejected fixes respected, a
        rationale that cites evidence (in prose, with no leaked tool-call syntax), no denied
        capability calls, and cost per round. The gate is
        at least 2/3 per scenario and 80% overall. Passing runs are recorded and replayed for free
        on every pull request.{" "}
        <a href={`${REPO}/tree/main/backend/evals`} target="_blank" rel="noreferrer" className="overview-link">
          Harness source
        </a>
      </p>

      {error && <p className="error">Failed to load eval results: {error}</p>}
      {!runs && !error && <p>Loading eval results…</p>}

      {runs && run && selected && (
        <>
          <section className="eval-summary">
            <div className="eval-stat">
              <span className="eval-stat-value">{pct(run.overall_pass_rate)}</span>
              <span className="eval-stat-label">trials passed ({passedCount(run).join("/")})</span>
            </div>
            <div className="eval-stat">
              <span className="eval-stat-value">{usd(run.total_cost_usd, 2)}</span>
              <span className="eval-stat-label">for the whole run</span>
            </div>
            <div className="eval-stat">
              <span className="eval-stat-value">{Object.keys(run.scenarios).length}</span>
              <span className="eval-stat-label">scenarios × 3 trials</span>
            </div>
            <div className="eval-stat">
              <span className={`eval-stat-value ${run.gate.failures.length ? "fail" : "pass"}`}>
                {run.gate.failures.length ? "FAIL" : "PASS"}
              </span>
              <span className="eval-stat-label">
                {runModel(selected)} · {formatRunTime(selected)}
              </span>
            </div>
          </section>

          {RUN_NOTES[runStamp(selected)] && <p className="eval-run-note">{RUN_NOTES[runStamp(selected)]}</p>}

          <h2>Scenarios</h2>
          <p className="evals-hint">Open a scenario to see every trial, its grades, and Claude's own rationale.</p>
          <div className="eval-scenarios">
            {SCENARIOS.map((def) => (
              <ScenarioRow key={def.scenario_id} def={def} result={run.scenarios[def.scenario_id]} />
            ))}
          </div>

          <h2>Run history</h2>
          <div className="eval-history-wrap">
            <table className="eval-history">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Model</th>
                  <th>Passed</th>
                  <th>Cost</th>
                  <th>What changed</th>
                </tr>
              </thead>
              <tbody>
                {RUNS.map(({ id }) => {
                  const r = runs.get(id);
                  if (!r) return null;
                  const [passed, total] = passedCount(r);
                  return (
                    <tr
                      key={id}
                      className={id === selected ? "selected" : undefined}
                      onClick={() => setSelected(id)}
                      tabIndex={0}
                      onKeyDown={(e) => e.key === "Enter" && setSelected(id)}
                    >
                      <td>{formatRunTime(id)}</td>
                      <td>{runModel(id)}</td>
                      <td>
                        {passed}/{total} ({pct(r.overall_pass_rate)})
                      </td>
                      <td>{usd(r.total_cost_usd, 2)}</td>
                      <td>{RUN_NOTES[runStamp(id)] ?? ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="evals-hint">Select a run to view its scenarios above.</p>
        </>
      )}

      <h2>What the evals caught</h2>
      <div className="eval-findings">
        {FINDINGS.map((f, i) => (
          <article key={f.title} className="eval-finding">
            <p className="overview-kicker">Finding {i + 1}</p>
            <h3>{f.title}</h3>
            <p>
              <strong>Found:</strong> {f.found}
            </p>
            <p>
              <strong>Cause:</strong> {f.cause}
            </p>
            <p>
              <strong>Fix:</strong> {f.fix}
            </p>
            <a href={f.adr} target="_blank" rel="noreferrer" className="overview-link">
              Decision record →
            </a>
          </article>
        ))}
      </div>
    </div>
  );
}
