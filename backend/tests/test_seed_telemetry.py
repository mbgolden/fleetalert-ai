from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

from fleetalert.agent.tools import execute_tool
from fleetalert.repositories import get_alert, get_machine
from fleetalert.seed_data import SEED_ALERTS, reseed_demo_data, seed_telemetry


def _snapshot(alert_id: str, window_minutes: int = 60) -> list[dict[str, Any]]:
    alert = get_alert(alert_id)
    assert alert is not None
    machine = get_machine(alert["machine_id"])
    assert machine is not None
    result = execute_tool(
        "get_telemetry_snapshot", {"window_minutes": window_minutes}, alert=alert, machine=machine
    )
    readings: list[dict[str, Any]] = result["readings"]
    return readings


def test_every_seeded_alert_has_telemetry_around_it(dynamodb_tables: None) -> None:
    reseed_demo_data()
    for alert in SEED_ALERTS:
        assert len(_snapshot(alert["alert_id"])) >= 10, alert["alert_id"]


def test_same_machine_alert_windows_never_overlap() -> None:
    by_machine: dict[str, list[datetime]] = {}
    for alert in SEED_ALERTS:
        by_machine.setdefault(alert["machine_id"], []).append(datetime.fromisoformat(alert["created_at"]))
    for times in by_machine.values():
        times.sort()
        for earlier, later in pairwise(times):
            assert later - earlier > timedelta(hours=6)


def test_telemetry_is_deterministic() -> None:
    assert seed_telemetry() == seed_telemetry()


def test_glitch_and_leak_tell_different_stories(dynamodb_tables: None) -> None:
    """The KB conflict (KB-001 glitch vs KB-002 leak) must be resolvable
    from evidence: ALERT-1004 is a lone spike with level flat, ALERT-1001 a
    sustained climb with level falling.
    """
    reseed_demo_data()

    glitch = _snapshot("ALERT-1004")
    glitch_temps = [float(r["signal_readings"]["coolant_temp_c"]) for r in glitch]
    assert sum(t > 100 for t in glitch_temps) == 1
    assert {float(r["signal_readings"]["coolant_level_pct"]) for r in glitch} == {96.0}

    leak = _snapshot("ALERT-1001")
    leak_temps = [float(r["signal_readings"]["coolant_temp_c"]) for r in leak]
    leak_levels = [float(r["signal_readings"]["coolant_level_pct"]) for r in leak]
    assert sum(t > 100 for t in leak_temps) >= 4
    assert min(leak_levels) < 85


def test_compressor_fault_shows_the_fault_state(dynamodb_tables: None) -> None:
    reseed_demo_data()
    states = {r["signal_readings"]["compressor_state"] for r in _snapshot("ALERT-1005")}
    assert "fault" in states
