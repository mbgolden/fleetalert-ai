import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type Alert, type DemoUsage, getUsage, listAlerts } from "../api";

const SEVERITY_LABEL: Record<string, string> = { low: "Low", medium: "Medium", high: "High" };

export default function AlertList() {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [usage, setUsage] = useState<DemoUsage | null>(null);

  useEffect(() => {
    listAlerts()
      .then((data) => setAlerts(data.alerts))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
    // Optional: the list still works if this fails.
    getUsage()
      .then(setUsage)
      .catch(() => setUsage(null));
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
          <li>
            Three entry points, one engine: the web UI, an inbound email every 4 hours, and a
            telemetry detector that raises its own alerts (try <em>Simulate inbound email</em> or{" "}
            <em>Run telemetry detector</em>)
          </li>
        </ul>
        {usage && (
          <p className={`usage-line${usage.exhausted ? " exhausted" : ""}`}>
            Today&apos;s demo budget: {usage.investigations} of {usage.investigation_cap} investigations,
            ${usage.cost_usd.toFixed(2)} of ${usage.cost_cap_usd.toFixed(2)} estimated spend
            {usage.exhausted && " (used up, resets at 00:00 UTC)"}
          </p>
        )}
        <Link to="/evals" className="overview-link overview-link-secondary">
          See the eval results &rarr;
        </Link>
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
                <span className="alert-type">
                  {alert.alert_type.replaceAll("_", " ")}
                  {alert.source === "email" && <span className="entry-chip entry-email card-chip">via email</span>}
                  {alert.source === "autonomous" && (
                    <span className="entry-chip entry-autonomous card-chip">autonomous</span>
                  )}
                </span>
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
