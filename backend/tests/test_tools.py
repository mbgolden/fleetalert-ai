import pytest

from fleetalert.agent.tools import execute_tool
from fleetalert.repositories import put_knowledge_base_entry, put_machine, put_telemetry_reading
from fleetalert.seed_data import SEED_KNOWLEDGE_BASE, SEED_MACHINES

ALERT = {
    "alert_id": "ALERT-1",
    "machine_id": "M-1001",
    "created_at": "2026-09-17T10:00:00+00:00",
}
MACHINE = SEED_MACHINES[0]


def _load_seed_data() -> None:
    for machine in SEED_MACHINES:
        put_machine(machine)
    for entry in SEED_KNOWLEDGE_BASE:
        put_knowledge_base_entry(entry)


def test_get_telemetry_snapshot_scopes_to_alert_machine_and_window(dynamodb_tables: None) -> None:
    put_telemetry_reading("M-1001", "2026-09-17T09:50:00+00:00", {"coolant_temp_f": 240})
    put_telemetry_reading("M-1001", "2026-09-17T12:00:00+00:00", {"coolant_temp_f": 198})
    put_telemetry_reading("M-1002", "2026-09-17T09:50:00+00:00", {"cabin_temp_f": 34})

    result = execute_tool(
        "get_telemetry_snapshot", {"window_minutes": 30}, alert=ALERT, machine=MACHINE
    )

    readings = result["readings"]
    assert len(readings) == 1
    assert readings[0]["signal_readings"]["coolant_temp_f"] == 240


def test_search_knowledge_base_uses_alert_machine_type(dynamodb_tables: None) -> None:
    _load_seed_data()

    result = execute_tool(
        "search_knowledge_base",
        {"symptom_description": "coolant temp spike"},
        alert=ALERT,
        machine=MACHINE,
    )

    assert {m["kb_id"] for m in result["matches"]} == {"KB-001", "KB-002"}


def test_get_service_history_uses_alert_machine_id(dynamodb_tables: None) -> None:
    _load_seed_data()

    result = execute_tool("get_service_history", {}, alert=ALERT, machine=MACHINE)

    assert [e["event_id"] for e in result["service_history"]] == ["SVC-1001-1"]


def test_propose_fix_just_acknowledges_receipt(dynamodb_tables: None) -> None:
    result = execute_tool(
        "propose_fix",
        {"fix_id": "restart_sensor", "description": "...", "confidence": 0.8},
        alert=ALERT,
        machine=MACHINE,
    )

    assert result == {"received": True, "fix_id": "restart_sensor"}


def test_unknown_tool_raises(dynamodb_tables: None) -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        execute_tool("delete_everything", {}, alert=ALERT, machine=MACHINE)
