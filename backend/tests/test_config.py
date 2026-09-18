import pytest

from fleetalert import config


def test_environment_defaults_to_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLEETALERT_ENV", raising=False)
    assert config.environment() == "demo"


def test_config_values_are_read_fresh_not_frozen_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of these being functions, not module constants --
    guards against reintroducing the "frozen at import time" bug.
    """
    monkeypatch.setenv("FLEETALERT_MODEL", "claude-opus-5")
    assert config.anthropic_model() == "claude-opus-5"

    monkeypatch.setenv("FLEETALERT_MODEL", "claude-haiku-4-5")
    assert config.anthropic_model() == "claude-haiku-4-5"


def test_optional_arns_are_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_SECRET_ARN", raising=False)
    monkeypatch.delenv("STATE_MACHINE_ARN", raising=False)
    assert config.anthropic_secret_arn() is None
    assert config.state_machine_arn() is None


def test_require_raises_a_clear_error_when_unset() -> None:
    with pytest.raises(RuntimeError, match="FOO is not set"):
        config.require(None, "FOO")


def test_require_passes_through_a_set_value() -> None:
    assert config.require("bar", "FOO") == "bar"
