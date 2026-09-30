import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type Alert, listAlerts } from "../api";

const SEVERITY_LABEL: Record<string, string> = { low: "Low", medium: "Medium", high: "High" };

export default function AlertList() {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAlerts()
      .then((data) => setAlerts(data.alerts))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  if (error) return <p className="error">Failed to load alerts: {error}</p>;
  if (!alerts) return <p>Loading alerts…</p>;

  return (
    <div className="alert-list">
      <section className="project-overview">
        <p className="overview-kicker">About this demo</p>
        <p>
          FleetAlert AI is an agentic investigation system for fleet-maintenance
          alerts. Claude reasons over telemetry and a knowledge base (RAG),
          then proposes a fix — a human must confirm before anything executes,
          enforced structurally by a Step Functions task-token callback, not
          just prompted.
        </p>
        <ul className="overview-points">
          <li>Only 3 whitelisted actions can ever run, checked twice</li>
          <li>A rejected fix triggers one more RAG-backed retry before escalating to a human</li>
          <li>Every model call, capability call and guardrail decision is traced as a structured span</li>
        </ul>
        <a
          href="https://10finger.dev/project/fleetalert-ai"
          target="_blank"
          rel="noreferrer"
          className="overview-link"
        >
          Read the full architecture &amp; guardrails &rarr;
        </a>
      </section>

      <h1>Demo Alerts</h1>
      <p>Pick one of the pre-seeded scenarios below to investigate.</p>
      <ul>
        {alerts.map((alert) => (
          <li key={alert.alert_id}>
            <Link to={`/alerts/${alert.alert_id}`} className="alert-card">
              <span className={`severity-badge severity-${alert.severity}`}>
                {SEVERITY_LABEL[alert.severity] ?? alert.severity}
              </span>
              <span className="alert-card-body">
                <strong>{alert.machine_name ?? alert.machine_id}</strong>
                <span className="alert-type">{alert.alert_type.replaceAll("_", " ")}</span>
              </span>
              <span className={`status-pill status-${alert.status}`}>
                {alert.status.replaceAll("_", " ")}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
