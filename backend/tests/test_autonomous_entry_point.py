"""The autonomous entry point: generated telemetry, the rule-based
detector, and the investigation it triggers (ADR-0020)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fleetalert import autonomous
from fleetalert.agent.loop import run_investigation
from fleetalert.autonomous import (
    AUTONOMOUS_ALERT_ID,
    MONITORED_MACHINE_ID,
    detect,
    generate_telemetry,
    run_detector,
)
from fleetalert.handlers import api_handler, autonomous_detector_handler
from fleetalert.repositories import get_alert, get_telemetry_snapshot, update_alert
from fleetalert.seed_data import reseed_demo_data
from tests.fakes import FakeAnthropicClient, response, tool_use_block

NOW = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)


class _Starts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, alert_id: str, entry_point: str) -> None:
        self.calls.append((alert_id, entry_point))


def _all_readings() -> list[dict[str, Any]]:
    return get_telemetry_snapshot(MONITORED_MACHINE_ID, "2000-01-01", "2100-01-01")


def test_generated_telemetry_covers_the_last_three_hours_and_expires() -> None:
    readings = generate_telemetry("normal", NOW)

    assert len(readings) == 19
    assert readings[0]["timestamp"] == (NOW - timedelta(hours=3)).isoformat()
    assert readings[-1]["timestamp"] == NOW.isoformat()
    assert all(r["expires_at"] == int((NOW + timedelta(days=2)).timestamp()) for r in readings)
    assert generate_telemetry("coolant_leak", NOW) == generate_telemetry("coolant_leak", NOW)


def test_normal_running_raises_nothing() -> None:
    assert detect(generate_telemetry("normal", NOW)) is None


def test_a_sustained_leak_is_a_high_severity_coolant_alert() -> None:
    detection = detect(generate_telemetry("coolant_leak", NOW))

    assert detection is not None
    assert detection.alert_type == "coolant_temp_spike"
    assert detection.rule == "coolant_temp_c >= 105"
    assert detection.tripped_readings >= autonomous.SUSTAINED_READINGS
    assert detection.severity == "high"


def test_a_single_spike_is_a_medium_severity_coolant_alert() -> None:
    detection = detect(generate_telemetry("sensor_glitch", NOW))

    assert detection is not None
    assert detection.tripped_readings == 1
    assert detection.peak_value == 121.0
    assert detection.severity == "medium"
    # The spike is an hour before now, so the readings after it show it passed.
    assert detection.first_tripped_at == (NOW - timedelta(hours=1)).isoformat()


def test_oil_pressure_decline_is_an_oil_alert() -> None:
    detection = detect(generate_telemetry("oil_pressure_decline", NOW))

    assert detection is not None
    assert detection.alert_type == "oil_pressure_warning"
    assert detection.rule == "oil_pressure_psi <= 25"
    assert detection.severity == "medium"


def test_the_button_always_generates_an_anomaly() -> None:
    for minute in range(len(autonomous.BUTTON_ROTATION)):
        profile = autonomous._slot(NOW + timedelta(minutes=minute), autonomous.BUTTON_ROTATION, timedelta(minutes=1))
        assert detect(generate_telemetry(profile, NOW)) is not None


def test_normal_run_stores_readings_and_starts_nothing(dynamodb_tables: None) -> None:
    reseed_demo_data()
    starts = _Starts()

    result = run_detector(starts, trigger="schedule", profile="normal", now=NOW)

    assert result == {"alert_raised": False, "readings": 19, "machine_id": MONITORED_MACHINE_ID}
    assert starts.calls == []
    assert get_alert(AUTONOMOUS_ALERT_ID) is None
    assert len(_all_readings()) == 19


def test_detection_opens_the_alert_and_starts_an_autonomous_investigation(dynamodb_tables: None) -> None:
    reseed_demo_data()
    starts = _Starts()

    result = run_detector(starts, trigger="schedule", profile="coolant_leak", now=NOW)

    assert result["alert_raised"] is True and result["started"] is True
    assert starts.calls == [(AUTONOMOUS_ALERT_ID, "autonomous")]
    alert = get_alert(AUTONOMOUS_ALERT_ID)
    assert alert is not None
    assert alert["status"] == "queued"
    assert alert["source"] == "autonomous"
    assert alert["machine_id"] == MONITORED_MACHINE_ID
    assert alert["alert_type"] == "coolant_temp_spike"
    assert alert["severity"] == "high"
    assert alert["created_at"] == alert["detection"]["first_tripped_at"]
    assert alert["detection"]["trigger"] == "schedule"


def test_a_second_run_replaces_the_trucks_readings(dynamodb_tables: None) -> None:
    reseed_demo_data()
    run_detector(_Starts(), trigger="schedule", profile="normal", now=NOW)

    run_detector(_Starts(), trigger="schedule", profile="normal", now=NOW + timedelta(minutes=7))

    readings = _all_readings()
    assert len(readings) == 19
    assert readings[-1]["timestamp"] == (NOW + timedelta(minutes=7)).isoformat()


def test_a_busy_alert_holds_the_run_without_touching_its_evidence(dynamodb_tables: None) -> None:
    reseed_demo_data()
    run_detector(_Starts(), trigger="schedule", profile="coolant_leak", now=NOW)
    update_alert(AUTONOMOUS_ALERT_ID, status="awaiting_confirmation")
    before = _all_readings()
    starts = _Starts()

    result = run_detector(starts, trigger="button", now=NOW + timedelta(minutes=5))

    assert result["started"] is False and "still being handled" in result["reason"]
    assert starts.calls == []
    assert _all_readings() == before


def test_an_exhausted_budget_detects_but_does_not_investigate(
    dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    reseed_demo_data()
    monkeypatch.setenv("FLEETALERT_DAILY_INVESTIGATION_CAP", "0")
    starts = _Starts()

    result = run_detector(starts, trigger="schedule", profile="sensor_glitch", now=NOW)

    assert result["alert_raised"] is True
    assert result["budget_exhausted"] is True
    assert starts.calls == []


def test_the_model_gets_the_detector_finding_and_clean_readings(dynamodb_tables: None) -> None:
    reseed_demo_data()
    run_detector(_Starts(), trigger="schedule", profile="sensor_glitch", now=NOW)
    client = FakeAnthropicClient(
        [
            response(tool_use_block("get_telemetry_snapshot", {"window_minutes": 60}, "t1")),
            response(
                tool_use_block(
                    "propose_fix",
                    {"fix_id": "restart_sensor", "confidence": 0.8, "description": "One 121 C reading, KB-001."},
                    "t2",
                )
            ),
        ]
    )

    result = run_investigation(AUTONOMOUS_ALERT_ID, client, entry_point="autonomous")

    assert result["outcome"] == "awaiting_confirmation"
    opening = client.messages.calls[0]["messages"][0]["content"]
    assert "rule-based telemetry detector" in opening
    assert "coolant_temp_c >= 105 tripped on 1 of 19 readings (peak 121.0)" in opening
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]["content"]
    readings = json.loads(tool_result)["readings"]
    assert len(readings) == 13  # +/- 60 minutes around the spike
    assert "expires_at" not in readings[0]


def test_scheduled_handler_runs_the_detector(dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch) -> None:
    reseed_demo_data()
    starts = _Starts()
    monkeypatch.setattr(autonomous_detector_handler, "enqueue_investigation", starts)

    result = autonomous_detector_handler.handler({}, None)

    assert "alert_raised" in result
    assert len(_all_readings()) == 19


def test_detect_route_starts_then_reports_busy(dynamodb_tables: None, monkeypatch: pytest.MonkeyPatch) -> None:
    reseed_demo_data()
    starts = _Starts()
    monkeypatch.setattr(api_handler, "enqueue_investigation", starts)

    first = api_handler.handler({"routeKey": "POST /demo/detect"}, None)
    second = api_handler.handler({"routeKey": "POST /demo/detect"}, None)
    status = api_handler.handler(
        {"routeKey": "GET /demo/alerts/{alert_id}/status", "pathParameters": {"alert_id": AUTONOMOUS_ALERT_ID}},
        None,
    )

    assert first["statusCode"] == 202
    assert json.loads(first["body"])["detection"]["alert_type"] in {"coolant_temp_spike", "oil_pressure_warning"}
    assert second["statusCode"] == 409
    assert starts.calls == [(AUTONOMOUS_ALERT_ID, "autonomous")]
    body = json.loads(status["body"])
    assert body["source"] == "autonomous"
    assert body["detection"]["rule"]


def test_the_detector_creates_its_truck_if_seeding_never_ran(dynamodb_tables: None) -> None:
    """The first live run failed: the truck was added to the seed data, but
    the live machines table hadn't been reseeded since. The detector now
    owns its truck."""
    from fleetalert.repositories import get_machine

    assert get_machine(MONITORED_MACHINE_ID) is None  # fresh tables, nothing seeded

    run_detector(_Starts(), trigger="button", profile="sensor_glitch", now=NOW)

    machine = get_machine(MONITORED_MACHINE_ID)
    assert machine is not None and machine["name"] == "Truck 31 - Engine"
