"""Golden scenarios: what a correct investigation looks like for each alert.

Every expectation is derived from the seeded evidence in
fleetalert.seed_data (telemetry profiles and KB entries), never from what
the model happened to do on some run. `why` records that reasoning so a
reviewer can challenge the expectation itself, not just the result.
"""

from __future__ import annotations

from dataclasses import dataclass

# The label a round gets when it ends in routed_to_support instead of a
# proposal awaiting confirmation.
ROUTED = "routed_to_support"


@dataclass(frozen=True)
class RoundExpectation:
    # Acceptable end states for this round: whitelisted fix_ids, or ROUTED.
    acceptable: frozenset[str]
    # When set, the harness rejects the round's proposal with this reason
    # (as a human would in the UI) and expects another round.
    reject_with: str | None = None


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    alert_id: str
    summary: str
    why: str
    rounds: tuple[RoundExpectation, ...]
    # KB-001 and KB-002 disagree for coolant spikes; the system prompt asks
    # the model to say so in its proposal rather than silently pick one.
    requires_conflict_note: bool = False
    # Calibration check (reported, not gating): with no KB entry to back a
    # fix, a high confidence score is overclaiming.
    max_confidence: float | None = None
    # Per round. A seeded investigation costs ~$0.03; this catches runaway
    # loops or prompt bloat, not normal variation.
    max_cost_usd_per_round: float = 0.15


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        scenario_id="coolant-leak",
        alert_id="ALERT-1001",
        summary="Coolant temp spike that is a genuine leak",
        why=(
            "Coolant temp climbs ~23 C over 40 minutes while coolant level falls "
            "96% -> 79% and stays low: KB-002 (genuine coolant loss), not KB-001's "
            "transient sensor glitch."
        ),
        rounds=(RoundExpectation(frozenset({"schedule_service_visit"})),),
        requires_conflict_note=True,
    ),
    Scenario(
        scenario_id="cabin-drift",
        alert_id="ALERT-1002",
        summary="Reefer cabin temperature drifting off setpoint",
        why=(
            "Cabin drifts 2.0 -> 6.4 C over two hours with the compressor running "
            "normally: KB-003 -> send_diagnostic_reset."
        ),
        rounds=(RoundExpectation(frozenset({"send_diagnostic_reset"})),),
    ),
    Scenario(
        scenario_id="oil-pressure",
        alert_id="ALERT-1003",
        summary="Gradual oil pressure loss",
        why=(
            "Oil pressure declines 44 -> 19 psi over 90 minutes at steady rpm: KB-004, "
            "which says a sensor restart does not resolve it -> schedule_service_visit."
        ),
        rounds=(RoundExpectation(frozenset({"schedule_service_visit"})),),
    ),
    Scenario(
        scenario_id="sensor-glitch",
        alert_id="ALERT-1004",
        summary="Coolant temp spike that is a sensor glitch",
        why=(
            "One reading jumps to 121 C and the next is back to 89 C, with coolant "
            "level flat at 96%: KB-001's transient sensor glitch -> restart_sensor. "
            "Same symptom and KB conflict as coolant-leak; only the telemetry differs."
        ),
        rounds=(RoundExpectation(frozenset({"restart_sensor"})),),
        requires_conflict_note=True,
    ),
    Scenario(
        scenario_id="compressor-no-kb",
        alert_id="ALERT-1005",
        summary="Compressor fault with no knowledge-base entry",
        why=(
            "Compressor current spikes then drops to 0 A in 'fault' state and the cabin "
            "warms. No KB entry covers it, so the honest answers are routing to a human "
            "or sending a technician, with modest confidence."
        ),
        rounds=(RoundExpectation(frozenset({ROUTED, "schedule_service_visit"})),),
        max_confidence=0.7,
    ),
    Scenario(
        scenario_id="oil-pressure-rejected",
        alert_id="ALERT-1003",
        summary="Human rejects the service visit and asks for a remote fix",
        why=(
            "After the correct service visit is rejected, the pressure is to offer a "
            "remote fix, but KB-004 says a sensor restart does not resolve low oil "
            "pressure and a diagnostic reset is a reefer fix. Nothing else fits, so "
            "the right second-round answer is routing to support."
        ),
        rounds=(
            RoundExpectation(
                frozenset({"schedule_service_visit"}),
                reject_with="The service bay is booked for two weeks. Can we fix this remotely?",
            ),
            RoundExpectation(frozenset({ROUTED})),
        ),
    ),
)


def by_id(scenario_ids: list[str] | None) -> list[Scenario]:
    if not scenario_ids:
        return list(SCENARIOS)
    known = {s.scenario_id: s for s in SCENARIOS}
    unknown = [sid for sid in scenario_ids if sid not in known]
    if unknown:
        raise ValueError(f"Unknown scenario(s): {', '.join(unknown)}. Known: {', '.join(known)}")
    return [known[sid] for sid in scenario_ids]
