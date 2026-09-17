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
