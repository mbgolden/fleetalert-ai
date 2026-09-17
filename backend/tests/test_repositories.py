from fleetalert.repositories import (
    append_audit_log,
    create_alert,
    get_alert,
    get_audit_trail,
    get_machine,
    get_service_history,
    get_telemetry_snapshot,
    put_knowledge_base_entry,
    put_machine,
    put_telemetry_reading,
    search_knowledge_base,
    update_alert,
)
from fleetalert.seed_data import SEED_KNOWLEDGE_BASE, SEED_MACHINES


def _load_seed_data() -> None:
    for machine in SEED_MACHINES:
        put_machine(machine)
    for entry in SEED_KNOWLEDGE_BASE:
        put_knowledge_base_entry(entry)


def test_put_and_get_machine(dynamodb_tables: None) -> None:
    put_machine(SEED_MACHINES[0])
    machine = get_machine("M-1001")
    assert machine is not None
    assert machine["machine_type"] == "diesel_engine"


def test_get_service_history_returns_seeded_events(dynamodb_tables: None) -> None:
    _load_seed_data()
    history = get_service_history("M-1003")
    assert len(history) == 1
    assert history[0]["event_id"] == "SVC-1003-1"


def test_get_service_history_missing_machine_returns_empty(dynamodb_tables: None) -> None:
    assert get_service_history("does-not-exist") == []


def test_telemetry_snapshot_window(dynamodb_tables: None) -> None:
    put_telemetry_reading("M-1001", "2026-09-17T10:00:00", {"coolant_temp_f": 195})
    put_telemetry_reading("M-1001", "2026-09-17T10:05:00", {"coolant_temp_f": 240})
    put_telemetry_reading("M-1001", "2026-09-17T11:00:00", {"coolant_temp_f": 198})

    snapshot = get_telemetry_snapshot(
        "M-1001", "2026-09-17T09:55:00", "2026-09-17T10:10:00"
    )

    assert len(snapshot) == 2
    assert {r["signal_readings"]["coolant_temp_f"] for r in snapshot} == {195, 240}


def test_search_knowledge_base_surfaces_ambiguous_conflicting_entries(
    dynamodb_tables: None,
) -> None:
    _load_seed_data()

    matches = search_knowledge_base("diesel_engine", "coolant temp spike")

    assert {m["kb_id"] for m in matches} == {"KB-001", "KB-002"}
    fixes = {m["known_fix"] for m in matches}
    assert fixes == {"restart_sensor", "schedule_service_visit"}


def test_search_knowledge_base_filters_by_machine_type(dynamodb_tables: None) -> None:
    _load_seed_data()

    matches = search_knowledge_base("refrigeration_unit", "temperature drift")

    assert [m["kb_id"] for m in matches] == ["KB-003"]


def test_alert_create_and_update(dynamodb_tables: None) -> None:
    create_alert(
        {
            "alert_id": "ALERT-1",
            "machine_id": "M-1001",
            "org_id": "org-demo",
            "alert_type": "coolant_temp_spike",
            "severity": "high",
            "status": "open",
            "created_at": "2026-09-17T10:05:00",
        }
    )

    update_alert("ALERT-1", status="investigating")

    alert = get_alert("ALERT-1")
    assert alert is not None
    assert alert["status"] == "investigating"


def test_audit_log_is_append_only_and_ordered(dynamodb_tables: None) -> None:
    append_audit_log("ALERT-1", "agent", "get_telemetry_snapshot", {"machine_id": "M-1001"})
    append_audit_log("ALERT-1", "agent", "search_knowledge_base", {"machine_type": "diesel_engine"})
    append_audit_log("ALERT-1", "human", "confirm", {"fix_id": "restart_sensor"})

    trail = get_audit_trail("ALERT-1")

    assert len(trail) == 3
    assert [e["action"] for e in trail] == [
        "get_telemetry_snapshot",
        "search_knowledge_base",
        "confirm",
    ]
    assert [e["actor"] for e in trail] == ["agent", "agent", "human"]
