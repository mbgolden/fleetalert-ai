import type { Detection } from "../api";

// What the rule-based detector saw when it raised this alert. It only
// checks thresholds; working out why is the agent's job.
const SIGNAL_LABELS: Record<string, string> = {
  coolant_temp_c: "coolant temperature (°C)",
  oil_pressure_psi: "oil pressure (psi)",
};

export default function DetectionCard({ detection }: { detection: Detection }) {
  const signal = SIGNAL_LABELS[detection.signal] ?? detection.signal.replaceAll("_", " ");
  return (
    <section className="detection-card">
      <p className="overview-kicker">Raised by the telemetry detector</p>
      <p className="detection-rule">
        Rule <code>{detection.rule}</code> tripped on {detection.tripped_readings} of{" "}
        {detection.total_readings} readings
      </p>
      <p className="detection-meta">
        Peak {signal}: {detection.peak_value} · first tripped{" "}
        {new Date(detection.first_tripped_at).toLocaleString()} · severity {detection.severity} ·{" "}
        {detection.trigger === "button" ? "run from the demo button" : "scheduled run"}
      </p>
      <p className="detection-note">
        No human raised this alert. The detector generated Truck 31's last 3 hours of telemetry
        and checked fixed thresholds, without knowing what caused the readings. The agent has to
        work out the cause from the evidence.
      </p>
    </section>
  );
}
