"""The autonomous entry point: live synthetic telemetry and a rule-based
detector. See docs/decisions/ADR-0020.

Every 4 hours (EventBridge -> autonomous_detector_handler), or when a
visitor presses "Run telemetry detector" (POST /demo/detect):
1. The generator writes the last 3 hours of readings for the monitored
   truck (M-1004), anchored to now, from one of a few profiles: normal
   running, a coolant leak, a sensor glitch, or oil pressure decline.
2. The detector checks those readings against fixed threshold rules. It
   never sees which profile produced them, so a missed or false detection
   is possible and visible.
3. If a rule trips, ALERT-1007 is reopened and investigated with
   entry_point="autonomous", through the same path as web and email.
   Normal readings raise nothing, and cost nothing.

The detector is deliberately simple and deterministic. Deciding whether
something is wrong stays cheap and explainable; the model is only asked to
work out why.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fleetalert import intake, metrics, repositories, seed_data
from fleetalert.intake import StartInvestigation

AUTONOMOUS_ALERT_ID = "ALERT-1007"
MONITORED_MACHINE_ID = "M-1004"

_WINDOW_MINUTES = 180
_STEP_MINUTES = 10
# Where in the window an anomaly starts, measured back from now, so the
# readings show what happened after it too (a glitch is only a glitch if
# the next reading is normal again).
_ANOMALY_LEAD_MINUTES = 60
# Generated readings expire (DynamoDB TTL on the telemetry table); seeded
# demo readings have no expiry.
_READING_TTL = timedelta(days=2)

Profile = Callable[[int, int], dict[str, Any]]


def _normal(m: int, i: int) -> dict[str, Any]:
    del m  # steady state: nothing depends on time
    return seed_data._diesel(
        i,
        coolant_temp_c=89 + seed_data._wobble(i, 1.0),
        coolant_level_pct=96,
        oil_pressure_psi=44 + seed_data._wobble(i, 0.8),
    )


PROFILES: dict[str, Profile] = {
    "normal": _normal,
    "coolant_leak": seed_data._coolant_leak,
    "sensor_glitch": seed_data._coolant_glitch,
    "oil_pressure_decline": seed_data._oil_pressure_decline,
}

# The schedule mostly sees healthy running; the button always shows an
# anomaly, so a visitor pressing it gets something to investigate.
SCHEDULE_ROTATION = ("normal", "coolant_leak", "normal", "sensor_glitch", "normal", "oil_pressure_decline")
BUTTON_ROTATION = ("coolant_leak", "sensor_glitch", "oil_pressure_decline")


@dataclass(frozen=True)
class Rule:
    alert_type: str
    signal: str
    comparison: str  # ">=" or "<="
    threshold: float
    severity: str
    # Used instead when at least SUSTAINED_READINGS readings trip the rule.
    sustained_severity: str

    def trips(self, value: float) -> bool:
        return value >= self.threshold if self.comparison == ">=" else value <= self.threshold


SUSTAINED_READINGS = 3

# Checked in order; the first rule that trips raises the alert.
RULES: tuple[Rule, ...] = (
    Rule("coolant_temp_spike", "coolant_temp_c", ">=", 105.0, "medium", "high"),
    Rule("oil_pressure_warning", "oil_pressure_psi", "<=", 25.0, "low", "medium"),
)


@dataclass(frozen=True)
class Detection:
    rule: str
    alert_type: str
    signal: str
    comparison: str
    threshold: float
    severity: str
    tripped_readings: int
    total_readings: int
    peak_value: float
    first_tripped_at: str


def generate_telemetry(profile: str, now: datetime) -> list[dict[str, Any]]:
    """The last 3 hours of readings for the monitored truck, every 10 min."""
    fn = PROFILES[profile]
    expires_at = int((now + _READING_TTL).timestamp())
    readings = []
    for i, offset in enumerate(range(-_WINDOW_MINUTES, 1, _STEP_MINUTES)):
        readings.append(
            {
                "machine_id": MONITORED_MACHINE_ID,
                "timestamp": (now + timedelta(minutes=offset)).isoformat(),
                "signal_readings": fn(offset + _ANOMALY_LEAD_MINUTES, i),
                "expires_at": expires_at,
            }
        )
    return readings


def detect(readings: list[dict[str, Any]]) -> Detection | None:
    for rule in RULES:
        tripped = [
            r
            for r in readings
            if rule.signal in r["signal_readings"] and rule.trips(float(r["signal_readings"][rule.signal]))
        ]
        if not tripped:
            continue
        values = [float(r["signal_readings"][rule.signal]) for r in tripped]
        return Detection(
            rule=f"{rule.signal} {rule.comparison} {rule.threshold:g}",
            alert_type=rule.alert_type,
            signal=rule.signal,
            comparison=rule.comparison,
            threshold=rule.threshold,
            severity=rule.sustained_severity if len(tripped) >= SUSTAINED_READINGS else rule.severity,
            tripped_readings=len(tripped),
            total_readings=len(readings),
            peak_value=max(values) if rule.comparison == ">=" else min(values),
            first_tripped_at=tripped[0]["timestamp"],
        )
    return None


def _slot(now: datetime, rotation: tuple[str, ...], period: timedelta) -> str:
    return rotation[int(now.timestamp() // period.total_seconds()) % len(rotation)]


def _monitored_machine() -> dict[str, Any]:
    return next(m for m in seed_data.SEED_MACHINES if m["machine_id"] == MONITORED_MACHINE_ID)


def _initial_alert() -> dict[str, Any]:
    return {
        "alert_id": AUTONOMOUS_ALERT_ID,
        "machine_id": MONITORED_MACHINE_ID,
        "org_id": "org-demo",
        "alert_type": "detector_pending",
        "severity": "low",
        "status": "open",
        "created_at": datetime.now(UTC).isoformat(),
        "source": "autonomous",
    }


# What the detector itself wrote on the alert. Everything else is left by
# an investigation, and Demo Reset drops it.
_DETECTED_FIELDS = (
    "alert_id",
    "machine_id",
    "org_id",
    "alert_type",
    "severity",
    "created_at",
    "source",
    "detection",
)


def reset_alert() -> None:
    """Demo Reset: put the detector's alert back to open, as detected.

    The alert isn't seed data (the detector creates it), so reseeding never
    touches it. It keeps what the detector found and loses what the
    investigation added, including its trace. A no-op if the detector has
    never raised anything.
    """
    alert = repositories.get_alert(AUTONOMOUS_ALERT_ID)
    if alert is None:
        return
    repositories.clear_spans_for_alert(AUTONOMOUS_ALERT_ID)
    # A whole-item put, like the seeded alerts get, so nothing lingers.
    repositories.create_alert({**{k: alert[k] for k in _DETECTED_FIELDS if k in alert}, "status": "open"})


def run_detector(
    start: StartInvestigation,
    *,
    trigger: str,
    profile: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Generate, detect, and investigate if a rule trips.

    Returns {"alert_raised": bool, "readings": n, "detection"?, and, when
    raised, the intake result (started, alert_id, reason...)}.
    """
    now = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
    current = repositories.get_alert(AUTONOMOUS_ALERT_ID)
    if current is not None and current.get("status") in intake.BUSY_STATUSES:
        # Checked before generating: new readings would land inside the
        # evidence window of the investigation still in flight.
        return {
            "alert_raised": False,
            "started": False,
            "alert_id": AUTONOMOUS_ALERT_ID,
            "reason": f"The detector's last alert is still being handled (status: {current.get('status')}).",
        }
    if profile is None:
        profile = (
            _slot(now, BUTTON_ROTATION, timedelta(minutes=1))
            if trigger == "button"
            else _slot(now, SCHEDULE_ROTATION, timedelta(hours=4))
        )
    # The detector owns its truck, so it makes sure the truck exists rather
    # than relying on demo seeding having run since the truck was added
    # (the first live run failed on exactly that). Idempotent put.
    repositories.put_machine(_monitored_machine())
    readings = generate_telemetry(profile, now)
    detection = detect(readings)
    metrics.emit_detector_run(detection.alert_type if detection else "normal")

    if detection is None and current is not None and current.get("status") == "open":
        # Demo Reset left the last alert open and uninvestigated, and the
        # truck's stored readings are its evidence. A normal run keeps them,
        # so a visitor who investigates the alert still finds the anomaly.
        return {
            "alert_raised": False,
            "readings": len(readings),
            "machine_id": MONITORED_MACHINE_ID,
            "kept_open_alert_evidence": True,
        }

    # The truck is the detector's alone; replacing its readings keeps two
    # runs a few minutes apart from interleaving two different stories.
    repositories.clear_telemetry(MONITORED_MACHINE_ID)
    repositories.put_telemetry_readings(readings)

    if detection is None:
        return {"alert_raised": False, "readings": len(readings), "machine_id": MONITORED_MACHINE_ID}

    result = intake.reopen_and_start(
        AUTONOMOUS_ALERT_ID,
        entry_point="autonomous",
        trigger=trigger,
        fields={
            "machine_id": MONITORED_MACHINE_ID,
            "alert_type": detection.alert_type,
            "severity": detection.severity,
            # The alert is "at" the first tripped reading, so the telemetry
            # capability's window is centred on the anomaly.
            "created_at": detection.first_tripped_at,
            "source": "autonomous",
            "detection": {**asdict(detection), "detected_at": now.isoformat(), "trigger": trigger},
        },
        start=start,
        busy_reason="The detector's last alert is still being handled",
        initial_alert=_initial_alert,
    )
    return {"alert_raised": True, "readings": len(readings), "detection": asdict(detection), **result}
