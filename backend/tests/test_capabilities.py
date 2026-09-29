"""Capabilities Engine: the builtin capabilities and the registry's guardrails."""

from typing import Any

import pytest

from fleetalert.capabilities import (
    AGENT_TIERS,
    Capability,
    CapabilityContext,
    CapabilityRegistry,
    SafetyTier,
    build_registry,
)
from fleetalert.capabilities.builtin import BUILTIN_CAPABILITIES
from fleetalert.repositories import (
    create_alert,
    get_alert,
    get_spans_for_alert,
    put_knowledge_base_entry,
    put_machine,
    put_telemetry_reading,
    update_alert,
)
from fleetalert.seed_data import SEED_KNOWLEDGE_BASE, SEED_MACHINES
from fleetalert.tracing import Tracer

ALERT: dict[str, Any] = {
    "alert_id": "ALERT-1",
    "machine_id": "M-1001",
    "org_id": "org-demo",
    "alert_type": "coolant_temp_spike",
    "severity": "high",
    "status": "investigating",
    "created_at": "2026-09-17T10:00:00+00:00",
}
MACHINE = SEED_MACHINES[0]


def _ctx(actor: str = "agent", alert: dict[str, Any] | None = None) -> CapabilityContext:
    alert = alert or ALERT
    return CapabilityContext(alert=alert, machine=MACHINE, tracer=Tracer.start(alert["alert_id"]), actor=actor)


def _load_seed_data() -> None:
    for machine in SEED_MACHINES:
        put_machine(machine)
    for entry in SEED_KNOWLEDGE_BASE:
        put_knowledge_base_entry(entry)


def _no_sleep_registry() -> CapabilityRegistry:
    return build_registry(retry_backoff_seconds=0, sleep=lambda _s: None)


# --- builtin capabilities -------------------------------------------------


def test_get_telemetry_snapshot_scopes_to_alert_machine_and_window(dynamodb_tables: None) -> None:
    put_telemetry_reading("M-1001", "2026-09-17T09:50:00+00:00", {"coolant_temp_f": 240})
    put_telemetry_reading("M-1001", "2026-09-17T12:00:00+00:00", {"coolant_temp_f": 198})
    put_telemetry_reading("M-1002", "2026-09-17T09:50:00+00:00", {"cabin_temp_f": 34})

    result = build_registry().invoke(
        "get_telemetry_snapshot", {"window_minutes": 30}, _ctx(), allowed_tiers=AGENT_TIERS
    )

    assert result.ok and result.output is not None
    assert [r["signal_readings"]["coolant_temp_f"] for r in result.output["readings"]] == [240]


def test_search_knowledge_base_uses_alert_machine_type(dynamodb_tables: None) -> None:
    _load_seed_data()
    result = build_registry().invoke(
        "search_knowledge_base", {"symptom_description": "coolant temp spike"}, _ctx(), allowed_tiers=AGENT_TIERS
    )
    assert result.ok and result.output is not None
    assert {m["kb_id"] for m in result.output["matches"]} == {"KB-001", "KB-002"}


def test_get_service_history_uses_alert_machine_id(dynamodb_tables: None) -> None:
    _load_seed_data()
    result = build_registry().invoke("get_service_history", {}, _ctx(), allowed_tiers=AGENT_TIERS)
    assert result.ok and result.output is not None
    assert [e["event_id"] for e in result.output["service_history"]] == ["SVC-1001-1"]


def test_propose_fix_just_acknowledges_receipt(dynamodb_tables: None) -> None:
    result = build_registry().invoke(
        "propose_fix",
        {"fix_id": "restart_sensor", "description": "...", "confidence": 0.8},
        _ctx(),
        allowed_tiers=AGENT_TIERS,
    )
    assert result.output == {"received": True, "fix_id": "restart_sensor"}


def test_request_confirmation_issues_a_token_and_moves_the_alert(dynamodb_tables: None) -> None:
    create_alert(ALERT)
    result = build_registry().invoke(
        "request_confirmation",
        {"fix_id": "restart_sensor", "description": "glitch", "confidence": 0.8},
        _ctx(actor="system"),
        allowed_tiers=frozenset({SafetyTier.PROPOSES_ACTION}),
    )
    assert result.ok and result.output is not None
    alert = get_alert("ALERT-1")
    assert alert is not None
    assert alert["status"] == "awaiting_confirmation"
    assert alert["confirmation_token"] == result.output["confirmation_token"]


def test_request_confirmation_reports_a_lost_race_instead_of_clobbering(dynamodb_tables: None) -> None:
    create_alert({**ALERT, "status": "resolved"})
    result = build_registry().invoke(
        "request_confirmation",
        {"fix_id": "restart_sensor", "description": "glitch", "confidence": 0.8},
        _ctx(actor="system"),
        allowed_tiers=frozenset({SafetyTier.PROPOSES_ACTION}),
    )
    assert result.output == {"status": "superseded", "fix_id": "restart_sensor"}
    assert get_alert("ALERT-1")["status"] == "resolved"  # type: ignore[index]


# --- registry guardrails --------------------------------------------------


def test_unknown_capability_is_a_structured_error_not_an_exception(dynamodb_tables: None) -> None:
    result = build_registry().invoke("delete_everything", {}, _ctx(), allowed_tiers=AGENT_TIERS)
    assert not result.ok
    assert "Unknown capability 'delete_everything'" in (result.error or "")


def test_invalid_input_is_rejected_before_the_handler_runs(dynamodb_tables: None) -> None:
    result = build_registry().invoke(
        "propose_fix", {"fix_id": "restart_sensor"}, _ctx(), allowed_tiers=AGENT_TIERS
    )
    assert not result.ok
    assert "'description' is a required property" in (result.error or "")
    assert "'confidence' is a required property" in (result.error or "")


@pytest.mark.parametrize(
    "bad_input",
    [
        {"window_minutes": 0},
        {"window_minutes": 181},
        {"window_minutes": "60"},
        {"window_minutes": 30, "machine_id": "M-1002"},  # can't redirect the read to another machine
    ],
)
def test_schema_bounds_are_enforced(dynamodb_tables: None, bad_input: dict[str, Any]) -> None:
    result = build_registry().invoke("get_telemetry_snapshot", bad_input, _ctx(), allowed_tiers=AGENT_TIERS)
    assert not result.ok


def test_agent_can_never_reach_execute_fix(dynamodb_tables: None) -> None:
    create_alert({**ALERT, "status": "awaiting_confirmation", "proposed_fix": "restart_sensor", "confirmation_token": "tok"})
    result = build_registry().invoke(
        "execute_fix", {"fix_id": "restart_sensor", "confirmation_token": "tok"}, _ctx(), allowed_tiers=AGENT_TIERS
    )
    assert not result.ok
    assert "not permitted" in (result.error or "")
    assert get_alert("ALERT-1")["status"] == "awaiting_confirmation"  # type: ignore[index]
    assert get_spans_for_alert("ALERT-1")[-1]["status"] == "denied"


def test_agent_cannot_call_system_only_capabilities_even_within_its_tiers(dynamodb_tables: None) -> None:
    create_alert(ALERT)
    result = build_registry().invoke(
        "request_confirmation",
        {"fix_id": "restart_sensor", "description": "x", "confidence": 0.5},
        _ctx(actor="agent"),
        allowed_tiers=AGENT_TIERS,
    )
    assert not result.ok
    assert get_alert("ALERT-1")["status"] == "investigating"  # type: ignore[index]


def test_agent_tools_expose_only_agent_callable_capabilities() -> None:
    names = [t["name"] for t in build_registry().agent_tools()]
    assert names == ["get_telemetry_snapshot", "search_knowledge_base", "get_service_history", "propose_fix"]


def test_executes_action_capability_cannot_be_registered_as_agent_callable() -> None:
    with pytest.raises(ValueError, match="never be agent-callable"):
        Capability(
            name="danger",
            description="",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            safety_tier=SafetyTier.EXECUTES_ACTION,
            idempotent=False,
            owner="test",
            handler=lambda _i, _c: {},
            agent_callable=True,
        )


def test_duplicate_registration_is_refused() -> None:
    registry = build_registry()
    with pytest.raises(ValueError, match="already registered"):
        registry.register(BUILTIN_CAPABILITIES[0])


def _flaky(fail_times: int, *, idempotent: bool, tier: SafetyTier = SafetyTier.READ_ONLY) -> tuple[Capability, list[int]]:
    calls: list[int] = []

    def handler(_input: dict[str, Any], _ctx: CapabilityContext) -> dict[str, Any]:
        calls.append(1)
        if len(calls) <= fail_times:
            raise ConnectionError("transient")
        return {"ok": True}

    capability = Capability(
        name="flaky",
        description="",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        safety_tier=tier,
        idempotent=idempotent,
        owner="test",
        handler=handler,
        agent_callable=tier != SafetyTier.EXECUTES_ACTION,
    )
    return capability, calls


def test_idempotent_read_is_retried_once_with_backoff(dynamodb_tables: None) -> None:
    slept: list[float] = []
    registry = CapabilityRegistry(retry_backoff_seconds=0.25, sleep=slept.append)
    capability, calls = _flaky(1, idempotent=True)
    registry.register(capability)

    result = registry.invoke("flaky", {}, _ctx(), allowed_tiers=AGENT_TIERS)

    assert result.ok and result.attempts == 2
    assert len(calls) == 2 and slept == [0.25]
    assert [s["status"] for s in get_spans_for_alert("ALERT-1")] == ["retry", "success"]


def test_retry_happens_only_once(dynamodb_tables: None) -> None:
    registry = CapabilityRegistry(retry_backoff_seconds=0, sleep=lambda _s: None)
    capability, calls = _flaky(5, idempotent=True)
    registry.register(capability)

    result = registry.invoke("flaky", {}, _ctx(), allowed_tiers=AGENT_TIERS)

    assert not result.ok and len(calls) == 2
    assert result.error_type == "ConnectionError"


@pytest.mark.parametrize(
    ("idempotent", "tier"),
    [(False, SafetyTier.READ_ONLY), (True, SafetyTier.PROPOSES_ACTION), (False, SafetyTier.EXECUTES_ACTION)],
)
def test_non_idempotent_or_non_read_capabilities_are_never_retried(
    dynamodb_tables: None, idempotent: bool, tier: SafetyTier
) -> None:
    registry = CapabilityRegistry(retry_backoff_seconds=0, sleep=lambda _s: None)
    capability, calls = _flaky(1, idempotent=idempotent, tier=tier)
    registry.register(capability)

    result = registry.invoke("flaky", {}, _ctx(actor="system"), allowed_tiers=frozenset(SafetyTier))

    assert not result.ok and len(calls) == 1


def test_handler_that_breaks_its_output_contract_fails_loudly(dynamodb_tables: None) -> None:
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="liar",
            description="",
            input_schema={"type": "object"},
            output_schema={"type": "object", "required": ["readings"]},
            safety_tier=SafetyTier.READ_ONLY,
            idempotent=True,
            owner="test",
            handler=lambda _i, _c: {"oops": 1},
            agent_callable=True,
        )
    )
    result = registry.invoke("liar", {}, _ctx(), allowed_tiers=AGENT_TIERS)
    assert not result.ok and "output contract" in (result.error or "")
    assert result.attempts == 1  # a contract bug, not a transient fault


def test_every_invocation_writes_a_span_with_latency_and_tier(dynamodb_tables: None) -> None:
    _load_seed_data()
    build_registry().invoke("get_service_history", {}, _ctx(), allowed_tiers=AGENT_TIERS)

    (span,) = get_spans_for_alert("ALERT-1")
    assert span["name"] == "get_service_history"
    assert span["kind"] == "capability"
    assert span["status"] == "success"
    assert span["actor"] == "agent"
    assert span["latency_ms"] is not None
    assert span["attributes"]["safety_tier"] == "read_only"


def test_confirmation_tokens_never_land_in_spans(dynamodb_tables: None) -> None:
    alert = {**ALERT, "status": "awaiting_confirmation", "proposed_fix": "restart_sensor", "confirmation_token": "secret-tok"}
    create_alert(alert)
    build_registry().invoke(
        "execute_fix",
        {"fix_id": "restart_sensor", "confirmation_token": "secret-tok"},
        _ctx(actor="system", alert=alert),
        allowed_tiers=frozenset({SafetyTier.EXECUTES_ACTION}),
    )
    assert "secret-tok" not in repr(get_spans_for_alert("ALERT-1"))


def test_execute_fix_rechecks_the_token_through_the_registry(dynamodb_tables: None) -> None:
    alert = {**ALERT, "status": "awaiting_confirmation", "proposed_fix": "restart_sensor", "confirmation_token": "tok"}
    create_alert(alert)
    update_alert("ALERT-1", status="awaiting_confirmation")
    result = build_registry().invoke(
        "execute_fix",
        {"fix_id": "restart_sensor", "confirmation_token": "wrong"},
        _ctx(actor="system", alert=alert),
        allowed_tiers=frozenset({SafetyTier.EXECUTES_ACTION}),
    )
    assert not result.ok and result.error_type == "GuardrailViolation"
    assert get_alert("ALERT-1")["status"] == "awaiting_confirmation"  # type: ignore[index]
