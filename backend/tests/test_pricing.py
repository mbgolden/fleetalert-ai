from types import SimpleNamespace

from fleetalert import pricing


def test_estimate_cost_for_known_model() -> None:
    usage = pricing.empty_usage()
    pricing.add_usage(usage, SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000))
    # 1M input at $2 + 100K output at $10/M
    assert pricing.estimate_cost_usd("claude-sonnet-5", usage) == 3.0


def test_cache_tokens_use_standard_multipliers() -> None:
    usage = pricing.empty_usage()
    pricing.add_usage(
        usage,
        SimpleNamespace(cache_creation_input_tokens=1_000_000, cache_read_input_tokens=1_000_000),
    )
    assert pricing.estimate_cost_usd("claude-sonnet-5", usage) == 2.5 + 0.2


def test_unknown_model_returns_none_not_a_guess() -> None:
    assert pricing.estimate_cost_usd("some-future-model", pricing.empty_usage()) is None


def test_missing_usage_fields_count_as_zero() -> None:
    usage = pricing.empty_usage()
    pricing.add_usage(usage, SimpleNamespace(input_tokens=None))
    assert usage == pricing.empty_usage()
