"""Synthetic seed data for the demo: fake fleet machines and a small KB.

SEED_KNOWLEDGE_BASE deliberately includes one ambiguous case: KB-001 and
KB-002 share the same machine_type + issue_pattern ("coolant temp spike" on
a diesel_engine) but disagree on the fix — one calls it a sensor glitch
(restart_sensor), the other genuine coolant loss (schedule_service_visit).
search_knowledge_base() will return both for that symptom; the agent loop
has to handle that conflict rather than the KB quietly resolving it.
"""

from typing import Any

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
