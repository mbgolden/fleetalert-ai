"""Synthetic seed data for the demo: fake fleet machines and a small KB.

SEED_KNOWLEDGE_BASE deliberately includes one ambiguous case: KB-001 and
KB-002 share the same machine_type + issue_pattern ("coolant temp spike" on
a diesel_engine) but disagree on the fix — one calls it a sensor glitch
(restart_sensor), the other genuine coolant loss (schedule_service_visit).
search_knowledge_base() will return both for that symptom; the agent loop
has to handle that conflict rather than the KB quietly resolving it.

The seeded telemetry is what resolves it: ALERT-1001 and ALERT-1004 share
that same symptom and the same two conflicting KB entries, but ALERT-1001's
readings show a sustained climb with coolant level falling (a real leak ->
KB-002) while ALERT-1004's show a single-sample spike with everything else
flat (a sensor glitch -> KB-001). See docs/decisions/ADR-0010.
"""

from datetime import datetime, timedelta
from typing import Any

from fleetalert import repositories

SEED_MACHINES: list[dict[str, Any]] = [
    {
        "machine_id": "M-1001",
        "machine_type": "diesel_engine",
        "org_id": "org-demo",
        "name": "Truck 14 - Engine",
        "service_history": [
            {
                "event_id": "SVC-1001-1",
                "date": "2026-06-02",
                "description": "Routine coolant system flush and inspection.",
            }
        ],
    },
    {
        "machine_id": "M-1002",
        "machine_type": "refrigeration_unit",
        "org_id": "org-demo",
        "name": "Trailer 7 - Reefer Unit",
        "service_history": [],
    },
    {
        "machine_id": "M-1003",
        "machine_type": "diesel_engine",
        "org_id": "org-demo",
        "name": "Truck 22 - Engine",
        "service_history": [
            {
                "event_id": "SVC-1003-1",
                "date": "2026-03-15",
                "description": "Replaced oil pressure sensor (unrelated fault).",
            }
        ],
    },
]

SEED_KNOWLEDGE_BASE: list[dict[str, Any]] = [
    {
        "kb_id": "KB-001",
        "machine_type": "diesel_engine",
        "issue_pattern": "coolant temp spike",
        "description": (
            "Coolant temperature sensor occasionally reports a transient spike "
            "with no corresponding rise in actual engine temperature -- a known "
            "sensor calibration glitch on this engine family."
        ),
        "known_fix": "restart_sensor",
    },
    {
        "kb_id": "KB-002",
        "machine_type": "diesel_engine",
        "issue_pattern": "coolant temp spike",
        "description": (
            "Sustained coolant temperature spike correlated with low coolant "
            "level -- indicates a genuine leak or coolant loss requiring "
            "physical inspection, not a sensor fault."
        ),
        "known_fix": "schedule_service_visit",
    },
    {
        "kb_id": "KB-003",
        "machine_type": "refrigeration_unit",
        "issue_pattern": "temperature drift",
        "description": (
            "Cabin temperature slowly drifting above the setpoint band while the "
            "unit controller's own return-air reading still shows setpoint -- the "
            "controller's sensor calibration has drifted, so it under-cools. A "
            "remote diagnostic reset re-runs controller self-calibration. Does not "
            "apply if the controller reading tracks the cabin probe: then the "
            "refrigeration circuit itself is at fault and needs a technician."
        ),
        "known_fix": "send_diagnostic_reset",
    },
    {
        "kb_id": "KB-004",
        "machine_type": "diesel_engine",
        "issue_pattern": "oil pressure warning",
        "description": "Low oil pressure warning, not resolved by sensor restart.",
        "known_fix": "schedule_service_visit",
    },
]

# The fixed set of demo scenarios visitors pick from (GET /demo/alerts) --
# no free-text input anywhere, per docs/decisions/ADR-0003. ALERT-1004
# reuses the same ambiguous coolant-temp-spike symptom as ALERT-1001 on the
# same machine, but the telemetry tells a different story (see the module
# docstring). ALERT-1005 has no matching KB entry at all, for a scenario
# where the agent genuinely doesn't have a confident answer to give.
#
# Alerts on the same machine are placed more than 6 hours apart so their
# telemetry windows (up to 180 minutes either side) never overlap -- each
# alert's evidence is its own.
SEED_ALERTS: list[dict[str, Any]] = [
    {
        "alert_id": "ALERT-1001",
        "machine_id": "M-1001",
        "org_id": "org-demo",
        "alert_type": "coolant_temp_spike",
        "severity": "high",
        "status": "open",
        "created_at": "2026-09-17T08:00:00+00:00",
    },
    {
        "alert_id": "ALERT-1002",
        "machine_id": "M-1002",
        "org_id": "org-demo",
        "alert_type": "temperature_drift",
        "severity": "medium",
        "status": "open",
        "created_at": "2026-09-17T08:05:00+00:00",
    },
    {
        "alert_id": "ALERT-1003",
        "machine_id": "M-1003",
        "org_id": "org-demo",
        "alert_type": "oil_pressure_warning",
        "severity": "low",
        "status": "open",
        "created_at": "2026-09-17T08:10:00+00:00",
    },
    {
        "alert_id": "ALERT-1004",
        "machine_id": "M-1001",
        "org_id": "org-demo",
        "alert_type": "coolant_temp_spike",
        "severity": "medium",
        "status": "open",
        "created_at": "2026-09-16T14:15:00+00:00",
    },
    {
        "alert_id": "ALERT-1005",
        "machine_id": "M-1002",
        "org_id": "org-demo",
        "alert_type": "compressor_fault",
        "severity": "high",
        "status": "open",
        "created_at": "2026-09-16T20:20:00+00:00",
    },
]

_TELEMETRY_SPAN_MINUTES = 180
_TELEMETRY_STEP_MINUTES = 10


def _wobble(i: int, amplitude: float) -> float:
    """Deterministic small variation so readings aren't perfectly flat."""
    return amplitude * (((i * 7) % 5) - 2) / 2


def _diesel(i: int, *, coolant_temp_c: float, coolant_level_pct: float, oil_pressure_psi: float) -> dict[str, Any]:
    return {
        "coolant_temp_c": round(coolant_temp_c, 1),
        "coolant_level_pct": round(coolant_level_pct, 1),
        "oil_pressure_psi": round(oil_pressure_psi, 1),
        "rpm": 1600 + (i * 37) % 120,
    }


def _reefer(
    cabin_temp_c: float,
    compressor_current_a: float,
    compressor_state: str,
    *,
    controller_reading_c: float | None = None,
) -> dict[str, Any]:
    # cabin_temp_c is an independent cabin probe; controller_reading_c is
    # the unit controller's own return-air sensor, which normally agrees.
    return {
        "cabin_temp_c": round(cabin_temp_c, 1),
        "controller_reading_c": round(cabin_temp_c if controller_reading_c is None else controller_reading_c, 1),
        "setpoint_c": 2.0,
        "compressor_current_a": round(compressor_current_a, 1),
        "compressor_state": compressor_state,
    }


def _coolant_glitch(m: int, i: int) -> dict[str, Any]:
    # ALERT-1004: one reading jumps and immediately returns; level and
    # everything else stay flat -- KB-001's "transient spike, no real rise".
    temp = 121.0 if m == 0 else 89 + _wobble(i, 1.0)
    return _diesel(i, coolant_temp_c=temp, coolant_level_pct=96, oil_pressure_psi=44 + _wobble(i, 0.8))


def _coolant_leak(m: int, i: int) -> dict[str, Any]:
    # ALERT-1001: sustained climb that tracks a falling coolant level --
    # KB-002's "correlated with low coolant level".
    if m < -40:
        temp, level = 89 + _wobble(i, 1.0), 96.0
    elif m <= 0:
        frac = (m + 40) / 40
        temp, level = 89 + 23 * frac, 96 - 17 * frac
    else:
        temp, level = 112 + min(4.0, m / 30), max(70.0, 79 - m / 20)
    return _diesel(i, coolant_temp_c=temp, coolant_level_pct=level, oil_pressure_psi=44 + _wobble(i, 0.8))


def _oil_pressure_decline(m: int, i: int) -> dict[str, Any]:
    # ALERT-1003: gradual oil pressure loss at steady rpm, not a jump --
    # consistent with KB-004 (not something a sensor restart fixes).
    if m < -90:
        oil = 44 + _wobble(i, 0.8)
    elif m <= 0:
        oil = 44 - 25 * (m + 90) / 90
    else:
        oil = 18.5 + _wobble(i, 0.4)
    return _diesel(i, coolant_temp_c=89 + _wobble(i, 1.0), coolant_level_pct=96, oil_pressure_psi=oil)


def _cabin_drift(m: int, i: int) -> dict[str, Any]:
    # ALERT-1002: the cabin probe drifts above setpoint while the controller's
    # own reading stays at setpoint, and the compressor eases off because the
    # controller thinks it's satisfied -- KB-003's calibration drift. (The
    # first version had no controller reading and the compressor at full
    # current throughout, which reads as a refrigeration fault; the first
    # live eval run caught that. See docs/decisions/ADR-0012.)
    controller = 2.0 + _wobble(i, 0.2)
    if m < -120:
        cabin, current = controller, 11.5 + _wobble(i, 0.4)
    elif m <= 0:
        frac = (m + 120) / 120
        cabin, current = 2.0 + 3.2 * frac, 11.5 - 3.0 * frac + _wobble(i, 0.3)
    else:
        cabin, current = 5.2 + min(0.6, m / 300), 8.5 + _wobble(i, 0.3)
    return _reefer(cabin, current, "running", controller_reading_c=controller)


def _compressor_fault(m: int, i: int) -> dict[str, Any]:
    # ALERT-1005: current spike then the compressor faults out and the cabin
    # starts warming -- no KB entry covers this, so the honest answer is
    # routing to a human.
    if m < -10:
        return _reefer(2.0 + _wobble(i, 0.2), 11.5 + _wobble(i, 0.4), "running")
    if m == -10:
        return _reefer(2.1, 24.0, "running")
    return _reefer(2.0 + 2.8 * m / 180, 0.0, "fault")


_TELEMETRY_PROFILES = {
    "ALERT-1001": _coolant_leak,
    "ALERT-1002": _cabin_drift,
    "ALERT-1003": _oil_pressure_decline,
    "ALERT-1004": _coolant_glitch,
    "ALERT-1005": _compressor_fault,
}


def seed_telemetry() -> list[dict[str, Any]]:
    """Readings every 10 minutes for 3 hours either side of each alert.

    Fully deterministic (no randomness), so the eval harness sees the same
    evidence every run.
    """
    readings: list[dict[str, Any]] = []
    for alert in SEED_ALERTS:
        profile = _TELEMETRY_PROFILES[alert["alert_id"]]
        created = datetime.fromisoformat(alert["created_at"])
        offsets = range(-_TELEMETRY_SPAN_MINUTES, _TELEMETRY_SPAN_MINUTES + 1, _TELEMETRY_STEP_MINUTES)
        for i, m in enumerate(offsets):
            readings.append(
                {
                    "machine_id": alert["machine_id"],
                    "timestamp": (created + timedelta(minutes=m)).isoformat(),
                    "signal_readings": profile(m, i),
                }
            )
    return readings


def reseed_demo_data() -> None:
    """Restores machines/KB/telemetry/alerts to their default seed state.

    Shared by scripts/seed_demo_data.py (run by hand against real AWS) and
    the demo API's own /demo/reset route (the frontend's "Reset Alerts"
    button) -- same safe-to-rerun put_item semantics either way. Also wipes
    each seeded alert's trace spans, since a stale trace from a previous
    investigation would contradict a freshly "open" alert on the UI's
    Investigation trace panel.
    """
    for machine in SEED_MACHINES:
        repositories.put_machine(machine)
    for entry in SEED_KNOWLEDGE_BASE:
        repositories.put_knowledge_base_entry(entry)
    repositories.put_telemetry_readings(seed_telemetry())
    for alert in SEED_ALERTS:
        repositories.clear_spans_for_alert(alert["alert_id"])
        repositories.create_alert(alert)
