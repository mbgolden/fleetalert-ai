"""Synthetic seed data for the demo: fake fleet machines and a small KB.

SEED_KNOWLEDGE_BASE deliberately includes one ambiguous case: KB-001 and
KB-002 share the same machine_type + issue_pattern ("coolant temp spike" on
a diesel_engine) but disagree on the fix — one calls it a sensor glitch
(restart_sensor), the other genuine coolant loss (schedule_service_visit).
search_knowledge_base() will return both for that symptom; the agent loop
has to handle that conflict rather than the KB quietly resolving it.
"""

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
        "description": "Cabin temperature slowly drifting outside setpoint band.",
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
# reuses the same ambiguous coolant-temp-spike symptom as ALERT-1001 but a
# different machine/severity, to show the conflict isn't a one-off fluke.
# ALERT-1005 has no matching KB entry at all, for a scenario where the
# agent genuinely doesn't have a confident answer to give.
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
        "created_at": "2026-09-17T08:15:00+00:00",
    },
    {
        "alert_id": "ALERT-1005",
        "machine_id": "M-1002",
        "org_id": "org-demo",
        "alert_type": "compressor_fault",
        "severity": "high",
        "status": "open",
        "created_at": "2026-09-17T08:20:00+00:00",
    },
]


def reseed_demo_data() -> None:
    """Restores machines/KB/alerts to their default seed state.

    Shared by scripts/seed_demo_data.py (run by hand against real AWS) and
    the demo API's own /demo/reset route (the frontend's "Reset Alerts"
    button) -- same safe-to-rerun put_item semantics either way. Also wipes
    each seeded alert's audit trail, since a stale trace from a previous
    investigation would contradict a freshly "open" alert on the UI's
    Investigation trace panel.
    """
    for machine in SEED_MACHINES:
        repositories.put_machine(machine)
    for entry in SEED_KNOWLEDGE_BASE:
        repositories.put_knowledge_base_entry(entry)
    for alert in SEED_ALERTS:
        repositories.clear_audit_trail(alert["alert_id"])
        repositories.create_alert(alert)
