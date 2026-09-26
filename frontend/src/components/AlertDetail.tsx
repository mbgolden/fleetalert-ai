import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

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

export default function AlertDetail() {
  const { alertId } = useParams<{ alertId: string }>();
  const [status, setStatus] = useState<AlertStatusResponse | null>(null);
  const [trail, setTrail] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const refresh = useCallback(async () => {
    if (!alertId) return;
    try {
      const [statusResp, auditResp] = await Promise.all([
        getAlertStatus(alertId),
        getAuditTrail(alertId),
      ]);
      setStatus(statusResp);
      setTrail(auditResp.audit_trail);
      if (TERMINAL_STATUSES.has(statusResp.status)) {
        stopPolling();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [alertId, stopPolling]);

  useEffect(() => {
    void refresh();
    return stopPolling;
  }, [refresh, stopPolling]);

  // Follows new trace entries and the eventual proposed-fix/outcome box
  // down as they appear, rather than making the visitor scroll to find
  // them -- keyed on trail.length (not the trail array itself, which is a
  // fresh reference every poll tick) so this only fires on real new
  // activity, not every 2s refresh.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [trail.length, status?.status]);

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
      await startInvestigation(alertId);
      stopPolling();
      pollRef.current = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    });

  const handleConfirm = () =>
    runAction(() => {
      if (!status?.confirmation_token) throw new Error("No confirmation token available yet.");
      return confirmFix(alertId, status.confirmation_token);
    });

  const handleReject = () => runAction(() => rejectFix(alertId, "Rejected from the demo UI."));

  return (
    <div className="alert-detail">
      <h1>{alertId}</h1>
      {error && <p className="error">{error}</p>}

      {status && (
        <p className={`status-pill status-${status.status}`}>{status.status.replaceAll("_", " ")}</p>
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
        {trail.length === 0 && <li className="timeline-empty">No activity yet.</li>}
      </ol>

      {status && (
        <>
          {status.status === "open" && (
            <button disabled={actionPending} onClick={handleInvestigate}>
              Investigate
            </button>
          )}

          {status.status === "awaiting_confirmation" && (
            <div className="proposed-fix">
              <h2>Proposed fix: {status.proposed_fix}</h2>
              {status.confidence && <p>Confidence: {Math.round(Number(status.confidence) * 100)}%</p>}
              {status.root_cause_summary && <p>{status.root_cause_summary}</p>}
              <div className="confirm-reject-controls">
                <button disabled={actionPending} onClick={handleConfirm}>
                  Confirm
                </button>
                <button disabled={actionPending} onClick={handleReject} className="reject">
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
        </>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
