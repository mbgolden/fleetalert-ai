import { type Span, num } from "../api";

// One investigation round = one trace. Rounds are grouped from the flat span
// list; within a round, capability calls nest under the model call that
// requested them.

const NAME_LABELS: Record<string, string> = {
  investigation_started: "Investigation started",
  model_call: "Claude",
  get_telemetry_snapshot: "Read telemetry",
  search_knowledge_base: "Searched knowledge base",
  get_service_history: "Read service history",
  propose_fix: "Proposed a fix",
  "guardrail.whitelist": "Whitelist check",
  "guardrail.not_previously_rejected": "Already-rejected check",
  "guardrail.truncated_output": "Cut-off tool call skipped",
  "guardrail.daily_budget": "Daily budget check",
  request_confirmation: "Requested human confirmation",
  awaiting_human_confirmation: "Paused for human confirmation",
  confirm: "Confirmed",
  reject: "Rejected",
  execute_fix: "Executed fix",
  route_to_support: "Routed to human support",
  execution_failed: "Execution failed",
  execution_refused: "Execution refused by a guardrail",
};

const OUTCOME_LABELS: Record<string, string> = {
  awaiting_confirmation: "proposed a fix",
  routed_to_support: "routed to support",
  resolved: "resolved",
  failed: "failed",
};

const STATUS_ICONS: Record<string, string> = {
  success: "✓",
  failure: "✕",
  retry: "↻",
  denied: "⛔",
};

interface Round {
  traceId: string;
  entryPoint: string;
  root: Span | null;
  spans: Span[];
}

function groupRounds(spans: Span[]): Round[] {
  const rounds = new Map<string, Round>();
  for (const span of spans) {
    let round = rounds.get(span.trace_id);
    if (!round) {
      round = { traceId: span.trace_id, entryPoint: span.entry_point, root: null, spans: [] };
      rounds.set(span.trace_id, round);
    }
    if (span.kind === "investigation") round.root = span;
    else round.spans.push(span);
  }
  return [...rounds.values()];
}

function formatLatency(value: unknown): string | null {
  const ms = num(value);
  if (ms === null) return null;
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

function formatCost(value: unknown): string | null {
  const usd = num(value);
  if (usd === null) return null;
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(3)}`;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function summarize(span: Span): string | null {
  const input = span.input ?? {};
  const output = span.output ?? {};
  if (typeof output.error === "string") return output.error;
  switch (span.name) {
    case "model_call": {
      const tools = list(output.tool_calls).map(String);
      return tools.length ? `→ ${tools.join(", ")}` : "no tool call";
    }
    case "investigation_started":
      return `via ${String(input.entry_point ?? span.entry_point)} · ${String(input.model ?? "")}`;
    case "get_telemetry_snapshot":
      return `${list(output.readings).length} readings, ±${String(input.window_minutes)} min around the alert`;
    case "search_knowledge_base": {
      const ids = list(output.matches).map((m) => String((m as Record<string, unknown>).kb_id));
      return `“${String(input.symptom_description)}” → ${ids.length ? ids.join(", ") : "no matches"}`;
    }
    case "get_service_history":
      return `${list(output.service_history).length} past service events`;
    case "propose_fix": {
      const confidence = num(input.confidence);
      return `${String(input.fix_id)}${confidence !== null ? ` · ${Math.round(confidence * 100)}% confidence` : ""}`;
    }
    case "guardrail.whitelist":
    case "guardrail.not_previously_rejected":
      return `${String(input.fix_id)} · ${span.status === "success" ? "passed" : "blocked"}`;
    case "request_confirmation":
    case "execute_fix":
    case "confirm":
      return String(input.fix_id ?? output.fix_id ?? "");
    case "route_to_support":
      return `${String(output.reason ?? "").replaceAll("_", " ")}${output.fix_id ? ` (${String(output.fix_id)})` : ""}`;
    case "reject":
      return input.reason ? String(input.reason) : null;
    default:
      return null;
  }
}

// Claude answers in light markdown; show it as plain prose rather than raw
// "##" and "**" markers (no markdown renderer for a quote block).
function plainText(markdown: string): string {
  return markdown
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

function hasPayload(span: Span): boolean {
  return Object.keys(span.input ?? {}).length > 0 || Object.keys(span.output ?? {}).length > 0;
}

function SpanRow({ span, nested }: { span: Span; nested?: Span[] }) {
  const summary = summarize(span);
  const latency = formatLatency(span.latency_ms);
  const attrs = span.attributes ?? {};
  const tokensIn = num(attrs.input_tokens);
  const tokensOut = num(attrs.output_tokens);
  const cost = span.kind === "model_call" ? formatCost(attrs.estimated_cost_usd) : null;
  // Claude's own words: text between tool calls, or a proposal's rationale.
  const text =
    span.kind === "model_call"
      ? String(span.output?.text ?? "")
      : span.name === "propose_fix"
        ? String(span.input?.description ?? "")
        : "";
  const tier = span.kind === "capability" ? String(attrs.safety_tier ?? "") : "";

  return (
    <li className={`span-row kind-${span.kind} status-${span.status} actor-${span.actor}`}>
      <div className="span-line">
        <span className="span-icon" aria-label={span.status}>
          {STATUS_ICONS[span.status] ?? "•"}
        </span>
        <span className="span-time">{new Date(span.timestamp).toLocaleTimeString()}</span>
        <span className="span-actor">{span.actor}</span>
        <span className="span-name">{NAME_LABELS[span.name] ?? span.name.replaceAll("_", " ")}</span>
        {tier && <span className={`tier-chip tier-${tier}`}>{tier.replace("_", " ")}</span>}
        {span.status !== "success" && <span className={`status-chip status-${span.status}`}>{span.status}</span>}
        <span className="span-meta">
          {tokensIn !== null && tokensOut !== null && `${tokensIn.toLocaleString()} → ${tokensOut.toLocaleString()} tok`}
          {cost && ` · ${cost}`}
          {latency && `${tokensIn !== null ? " · " : ""}${latency}`}
        </span>
      </div>
      {summary && <div className="span-summary">{summary}</div>}
      {text && <blockquote className="span-text">{plainText(text)}</blockquote>}
      {hasPayload(span) && (
        <details className="span-payload">
          <summary>input / output</summary>
          <pre>{JSON.stringify({ input: span.input, output: span.output }, null, 2)}</pre>
        </details>
      )}
      {nested && nested.length > 0 && (
        <ol className="span-children">
          {nested.map((child) => (
            <SpanRow key={child.span_id} span={child} />
          ))}
        </ol>
      )}
    </li>
  );
}

function RoundCard({ round, index, live }: { round: Round; index: number; live: boolean }) {
  const modelCalls = round.spans.filter((s) => s.kind === "model_call");
  const modelCallIds = new Set(modelCalls.map((s) => s.span_id));
  const children = new Map<string, Span[]>();
  const topLevel: Span[] = [];
  for (const span of round.spans) {
    if (span.parent_span_id && modelCallIds.has(span.parent_span_id)) {
      children.set(span.parent_span_id, [...(children.get(span.parent_span_id) ?? []), span]);
    } else {
      topLevel.push(span);
    }
  }

  // Rounds on one alert can come from different entry points (web, email),
  // so only call a round "after rejection" when it actually followed one.
  const started = round.spans.find((s) => s.name === "investigation_started");
  const afterRejection = (num(started?.input?.rejected_fixes) ?? 0) > 0;
  const rootAttrs = round.root?.attributes ?? {};
  const outcome = round.root ? String(round.root.output?.outcome ?? "") : "";
  const cost =
    formatCost(rootAttrs.estimated_cost_usd) ??
    formatCost(modelCalls.reduce((sum, s) => sum + (num(s.attributes?.estimated_cost_usd) ?? 0), 0));
  const latency = formatLatency(round.root?.latency_ms);
  // What happened after the round's own outcome, in this same trace.
  const followUps = round.spans
    .filter(
      (s) =>
        s.status === "success" &&
        (s.kind === "human_action" || s.name === "execute_fix"),
    )
    .map((s) => (s.name === "reject" ? "rejected" : s.name === "confirm" ? "confirmed" : "fix executed"));

  return (
    <section className="round-card">
      <header className="round-header">
        <span className="round-title">Round {index + 1}</span>
        <span className={`entry-chip entry-${round.entryPoint}`}>{round.entryPoint}</span>
        {afterRejection && <span className="round-note">after rejection</span>}
        <span className="round-outcome">
          {round.root ? (OUTCOME_LABELS[outcome] ?? outcome) : live ? "in progress…" : "incomplete"}
          {followUps.map((f) => ` → ${f}`).join("")}
        </span>
        <span className="round-meta">
          {modelCalls.length} model call{modelCalls.length === 1 ? "" : "s"}
          {latency && ` · ${latency}`}
          {cost && ` · ${cost}`}
        </span>
      </header>
      <ol className="span-list">
        {topLevel.map((span) => (
          <SpanRow key={span.span_id} span={span} nested={children.get(span.span_id)} />
        ))}
      </ol>
    </section>
  );
}

export default function TraceView({ spans, working }: { spans: Span[]; working: boolean }) {
  const rounds = groupRounds(spans);
  if (rounds.length === 0) return null;
  return (
    <div className="trace-view">
      {rounds.map((round, i) => (
        <RoundCard key={round.traceId} round={round} index={i} live={working && i === rounds.length - 1} />
      ))}
    </div>
  );
}
