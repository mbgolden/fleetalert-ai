import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  type AlertStatus,
  type AlertStatusResponse,
  type AuditLogEntry,
  confirmFix,
  getAlertStatus,
  getAuditTrail,
  rejectFix,
  startInvestigation,
} from "../api";

const TERMINAL_STATUSES = new Set<AlertStatus>([
  "resolved",
  "rejected",
  "routed_to_support",
  "failed",
]);
const POLL_INTERVAL_MS = 2000;
const STALLED_AFTER_S = 45;

// Plain-English version of the latest audit entry, shown while work is in
// flight so the visitor can see what is happening right now.
const ACTIVITY_LABELS: Record<string, string> = {
  investigation_started: "Starting the investigation",
  get_telemetry_snapshot: "Reading machine telemetry",
  search_knowledge_base: "Searching the knowledge base",
  get_service_history: "Reviewing service history",
  propose_fix: "Preparing a proposed fix",
  request_confirmation: "Preparing the proposal for review",
  reject: "Looking for an alternative fix",
  confirm: "Executing the confirmed fix",
};

export default function AlertDetail() {
  const { alertId } = useParams<{ alertId: string }>();
  const [status, setStatus] = useState<AlertStatusResponse | null>(null);
  const [trail, setTrail] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  // True from clicking Investigate until the backend reports it's running.
  const [starting, setStarting] = useState(false);
  // True from clicking Confirm until the fix has actually executed.
  const [executing, setExecuting] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const refreshRef = useRef<() => Promise<void>>(async () => {});
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(() => void refreshRef.current(), POLL_INTERVAL_MS);
  }, [stopPolling]);

  const refresh = useCallback(async () => {
    if (!alertId) return;
    try {
      const [statusResp, auditResp] = await Promise.all([
        getAlertStatus(alertId),
        getAuditTrail(alertId),
      ]);
      setStatus(statusResp);
      setTrail(auditResp.audit_trail);
      if (statusResp.status !== "open") setStarting(false);
      if (statusResp.status !== "awaiting_confirmation") setExecuting(false);
      if (TERMINAL_STATUSES.has(statusResp.status)) {
        stopPolling();
      } else if (statusResp.status === "investigating" && pollRef.current === null) {
        // e.g. the page was opened or reloaded mid-investigation
        startPolling();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [alertId, startPolling, stopPolling]);

  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  useEffect(() => {
    void refresh();
    return stopPolling;
  }, [refresh, stopPolling]);

  const working = status?.status === "investigating" || starting || executing;

  // Ticks once a second, only while there is something to time.
  useEffect(() => {
    if (!working) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [working]);

  // Follows new trace entries and the eventual proposed-fix/outcome box
  // down as they appear, rather than making the visitor scroll to find
  // them -- keyed on trail.length (not the trail array itself, which is a
  // fresh reference every poll tick) so this only fires on real new
  // activity, not every 2s refresh.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [trail.length, status?.status, working]);

  if (!alertId) return null;

  const runAction = async (action: () => Promise<unknown>) => {
    setActionPending(true);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionPending(false);
    }
  };

  const handleInvestigate = () =>
    runAction(async () => {
      setStarting(true);
      try {
        await startInvestigation(alertId);
      } catch (err) {
        setStarting(false);
        throw err;
      }
      startPolling();
    });

  const handleConfirm = () =>
    runAction(async () => {
      if (!status?.confirmation_token) throw new Error("No confirmation token available yet.");
      await confirmFix(alertId, status.confirmation_token);
      setExecuting(true);
      startPolling();
    });

  const handleReject = () =>
    runAction(async () => {
      await rejectFix(alertId, "Rejected from the demo UI.");
      startPolling();
    });

  const lastEntry = trail.length > 0 ? trail[trail.length - 1] : null;
  const lastEntryAt = lastEntry ? new Date(lastEntry.timestamp).getTime() : null;
  const sinceLastUpdate = lastEntryAt ? Math.max(0, Math.round((now - lastEntryAt) / 1000)) : 0;
  const stalled = working && lastEntryAt !== null && sinceLastUpdate > STALLED_AFTER_S;
  const activityLabel = executing
    ? ACTIVITY_LABELS.confirm
    : lastEntry
      ? (ACTIVITY_LABELS[lastEntry.action] ?? "Working")
      : ACTIVITY_LABELS.investigation_started;

  const isTerminal = status !== null && TERMINAL_STATUSES.has(status.status);
  const pillLabel = starting || executing ? "working" : (status?.status.replaceAll("_", " ") ?? "");

  return (
    <div className="alert-detail">
      <h1>{alertId}</h1>
      {error && <p className="error">{error}</p>}

      {status && (
        <p className={`status-pill status-${status.status}${working ? " working" : ""}`}>
          {working && <span className="spinner" aria-hidden="true" />}
          {pillLabel}
        </p>
      )}

      <h2>Investigation trace</h2>
      <ol className="timeline">
        {trail.map((entry) => (
          <li key={entry.log_id} className={`timeline-entry actor-${entry.actor}`}>
            <span className="timeline-time">{new Date(entry.timestamp).toLocaleTimeString()}</span>
            <span className="timeline-actor">{entry.actor}</span>
            <span className="timeline-action">{entry.action.replaceAll("_", " ")}</span>
            {Object.keys(entry.details).length > 0 && (
              <pre className="timeline-details">{JSON.stringify(entry.details, null, 2)}</pre>
            )}
          </li>
        ))}
        {trail.length === 0 && !working && <li className="timeline-empty">No activity yet.</li>}
        {working && (
          <li className="timeline-working" role="status" aria-live="polite">
            <span className="spinner" aria-hidden="true" />
            <span>
              {stalled
                ? `Still working — no update for ${sinceLastUpdate}s, this is taking longer than usual…`
                : `${activityLabel}…`}
            </span>
            {lastEntryAt !== null && !stalled && (
              <span className="timeline-working-time">{sinceLastUpdate}s since last update</span>
            )}
          </li>
        )}
      </ol>

      {status && (
        <>
          {status.status === "open" && (
            <button disabled={actionPending || starting} onClick={handleInvestigate}>
              {starting ? "Starting…" : "Investigate"}
            </button>
          )}

          {status.status === "awaiting_confirmation" && (
            <div className="proposed-fix">
              <h2>Proposed fix: {status.proposed_fix}</h2>
              {status.confidence && <p>Confidence: {Math.round(Number(status.confidence) * 100)}%</p>}
              {status.root_cause_summary && <p>{status.root_cause_summary}</p>}
              <div className="confirm-reject-controls">
                <button disabled={actionPending || executing} onClick={handleConfirm}>
                  {executing ? "Executing…" : "Confirm"}
                </button>
                <button
                  disabled={actionPending || executing}
                  onClick={handleReject}
                  className="reject"
                >
                  Reject
                </button>
              </div>
            </div>
          )}

          {status.status === "resolved" && <p className="outcome resolved">Fix applied and resolved.</p>}
          {status.status === "rejected" && <p className="outcome rejected">Fix was rejected.</p>}
          {status.status === "routed_to_support" && (
            <p className="outcome routed">No safe automated fix — routed to human support.</p>
          )}
          {status.status === "failed" && (
            <p className="outcome rejected">
              Investigation failed after retries. See the trace above, or check CloudWatch.
            </p>
          )}

          {isTerminal && (
            <Link to="/" className="back-link">
              ← Back to alerts
            </Link>
          )}
        </>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
