"""Daily cost guard for the public demo. See docs/decisions/ADR-0017.

Every investigation round, from any entry point, reserves a slot in today's
(UTC) usage row before it calls the model, and adds its estimated cost when
it ends. A round is refused once either daily cap is reached. The check is
one conditional write, so concurrent rounds can't both squeeze past it.

This bounds the demo's own spend. The Anthropic workspace spend limit is
the hard backstop outside the app, and the CloudWatch spend alarm is the
early warning.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fleetalert import config, repositories

_KEEP_DAYS = 90  # usage rows expire via DynamoDB TTL


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def _expires_at() -> int:
    return int((datetime.now(UTC) + timedelta(days=_KEEP_DAYS)).timestamp())


def usage() -> dict[str, Any]:
    """Today's usage and caps, for the UI and the entry points' pre-checks."""
    row = repositories.get_usage(today())
    rounds = int(row.get("investigations", 0))
    cost = float(row.get("cost_usd", 0))
    round_cap = config.daily_investigation_cap()
    cost_cap = config.daily_cost_cap_usd()
    return {
        "day": today(),
        "investigations": rounds,
        "investigation_cap": round_cap,
        "cost_usd": round(cost, 4),
        "cost_cap_usd": cost_cap,
        "exhausted": rounds >= round_cap or cost >= cost_cap,
        "resets_at": f"{(datetime.now(UTC).date() + timedelta(days=1)).isoformat()}T00:00:00+00:00",
    }


def exhausted_message() -> str:
    u = usage()
    return (
        f"Today's demo budget is used up ({u['investigations']} investigations, "
        f"${u['cost_usd']:.2f} of ${u['cost_cap_usd']:.2f}). It resets at 00:00 UTC."
    )


def reserve_round() -> bool:
    max_rounds, max_cost = config.daily_investigation_cap(), config.daily_cost_cap_usd()
    if max_rounds <= 0 or max_cost <= 0:
        # A zero cap is "off". Checked here because the conditional write
        # lets the day's first round through before its row exists.
        return False
    return repositories.reserve_usage(
        today(), max_rounds=max_rounds, max_cost_usd=max_cost, expires_at=_expires_at()
    )


def record_cost(cost_usd: float | None) -> None:
    if cost_usd:
        repositories.add_usage_cost(today(), cost_usd, expires_at=_expires_at())
