"""Token prices for estimating what an investigation cost.

USD per million tokens. Cache pricing uses Anthropic's standard multipliers
(write = 1.25x input, read = 0.1x input). Update this table when the model
changes -- an unknown model returns None rather than a wrong number.
"""

from __future__ import annotations

from typing import Any

MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
}

USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def empty_usage() -> dict[str, int]:
    return dict.fromkeys(USAGE_FIELDS, 0)


def add_usage(totals: dict[str, int], usage: Any) -> None:
    """Accumulate an SDK `response.usage` object into `totals`."""
    for field in USAGE_FIELDS:
        totals[field] += int(getattr(usage, field, 0) or 0)


def estimate_cost_usd(model: str, usage: dict[str, int]) -> float | None:
    prices = MODEL_PRICING.get(model)
    if prices is None:
        return None
    per_token_in = prices["input"] / 1_000_000
    per_token_out = prices["output"] / 1_000_000
    cost = (
        usage["input_tokens"] * per_token_in
        + usage["output_tokens"] * per_token_out
        + usage["cache_creation_input_tokens"] * per_token_in * 1.25
        + usage["cache_read_input_tokens"] * per_token_in * 0.1
    )
    return round(cost, 6)
