import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ActivityEvent, getActivity } from "../api";

// Every decision and end state across all alerts, newest first (ADR-0022).
// Built from the same trace spans as each alert's own page.

type Filter = "all" | "end_state" | "guardrail" | "human" | "outcome";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "end_state", label: "End states" },
  { id: "guardrail", label: "Guardrails" },
  { id: "human", label: "People" },
  { id: "outcome", label: "Proposals" },
];

const END_STATES: { id: string; label: string }[] = [
  { id: "resolved", label: "Resolved" },
  { id: "routed_to_support", label: "Routed to support" },
  { id: "failed", label: "Failed" },
  { id: "refused", label: "Refused" },
];

const REFRESH_MS = 20_000;

function tone(event: ActivityEvent): string {
  if (event.end_state === "resolved") return "good";
  if (event.end_state === "routed_to_support") return "warn";
  if (event.end_state === "failed" || event.end_state === "refused") return "bad";
  if (event.status === "failure" || event.status === "denied") return "bad";
  if (event.category === "guardrail") return "quiet";
  return "info";
}

const ICONS: Record<string, string> = { good: "✓", warn: "↗", bad: "✕", quiet: "·", info: "•" };

function dayKey(iso: string): string {
  return new Date(iso).toDateString();
}

function dayLabel(iso: string): string {
  const day = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86_400_000);
  if (day.toDateString() === today.toDateString()) return "Today";
  if (day.toDateString() === yesterday.toDateString()) return "Yesterday";
  return day.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export default function ActivityPage() {
  const [events, setEvents] = useState<ActivityEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const load = useCallback(() => {
    getActivity()
      .then((data) => {
        setEvents(data.events);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const today = new Date().toDateString();
  const todaysEndStates = (events ?? []).filter((e) => e.end_state && dayKey(e.timestamp) === today);
  const shown = (events ?? []).filter((e) => filter === "all" || e.category === filter);

  // Group consecutive events by day for the date headers.
  const groups: { day: string; label: string; items: ActivityEvent[] }[] = [];
  for (const event of shown) {
    const key = dayKey(event.timestamp);
    const last = groups[groups.length - 1];
    if (last && last.day === key) last.items.push(event);
    else groups.push({ day: key, label: dayLabel(event.timestamp), items: [event] });
  }

  return (
    <div className="activity-page">
      <h1>Activity</h1>
      <p className="activity-intro">
        Every decision and end state across all alerts, newest first: guardrail checks, proposals,
        human confirms and rejects, and how each alert ended. It's built from the same trace each
        alert page shows, and refreshes every 20 seconds.
      </p>

      <section className="activity-summary" aria-label="End states today">
        {END_STATES.map((s) => (
          <div key={s.id} className={`activity-stat end-${s.id}`}>
            <span className="activity-stat-value">
              {todaysEndStates.filter((e) => e.end_state === s.id).length}
            </span>
            <span className="activity-stat-label">{s.label} today</span>
          </div>
        ))}
      </section>

      <div className="activity-filters" role="group" aria-label="Show">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            className={`filter-chip${filter === f.id ? " active" : ""}`}
            aria-pressed={filter === f.id}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && <p className="error">Couldn't load activity: {error}</p>}
      {!events && !error && <p>Loading activity…</p>}
      {events && shown.length === 0 && (
        <p className="activity-empty">
          Nothing here yet. Investigate an alert, or try Simulate inbound email or Run telemetry
          detector, and its decisions will appear here.
        </p>
      )}

      {groups.map((group) => (
        <section key={group.day} className="activity-day">
          <h2 className="activity-day-label">{group.label}</h2>
          <ol className="activity-list">
            {group.items.map((event) => {
              const t = tone(event);
              return (
                <li key={`${event.trace_id}-${event.timestamp}-${event.title}`} className={`activity-row tone-${t}`}>
                  <span className="activity-icon" aria-hidden="true">
                    {ICONS[t]}
                  </span>
                  <div className="activity-body">
                    <p className="activity-title">
                      {event.title}
                      {event.count > 1 && <span className="activity-count">×{event.count}</span>}
                    </p>
                    {event.detail && <p className="activity-detail">{event.detail}</p>}
                    <p className="activity-meta">
                      <Link to={`/alerts/${event.alert_id}`} className="activity-alert">
                        {event.alert_id}
                      </Link>
                      {event.machine_name && <span>{event.machine_name}</span>}
                      <span className={`entry-chip entry-${event.entry_point}`}>{event.entry_point}</span>
                    </p>
                  </div>
                  <time className="activity-time" dateTime={event.timestamp}>
                    {timeLabel(event.timestamp)}
                  </time>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
