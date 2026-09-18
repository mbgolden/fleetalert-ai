"""All environment-derived configuration in one place.

Anyone auditing "what can this app be configured with" has one file to
check, instead of grepping for os.environ across every module. Safety
guardrails (the fix-type whitelist, max loop iterations) deliberately live
elsewhere -- fleetalert.whitelist and fleetalert.agent.guardrails -- since
those aren't meant to be casually tuned via environment variables the way
operational config is; conflating the two would make it too easy to loosen
a guardrail by just editing an env var.

Every value below is a function, not a module-level constant, and that's
deliberate: os.environ.get(...) read once at import time gets frozen into
whatever the environment happened to be at that moment, which both breaks
tests (monkeypatch.setenv after the module's already imported has no
effect on an already-computed constant) and is a real footgun generally.
Call these at the point of use, not at module load time.
"""

from __future__ import annotations

import os

PROJECT_NAME = "fleetalert-ai"  # not env-derived -- genuinely constant


def environment() -> str:
    return os.environ.get("FLEETALERT_ENV", "demo")


def aws_region() -> str:
    return os.environ.get("AWS_REGION", "us-east-1")


def anthropic_model() -> str:
    return os.environ.get("FLEETALERT_MODEL", "claude-sonnet-5")


def anthropic_secret_arn() -> str | None:
    """Set by Terraform on the agent-loop Lambda only; None elsewhere."""
    return os.environ.get("ANTHROPIC_SECRET_ARN")


def state_machine_arn() -> str | None:
    """Set by Terraform on the API Lambda only; None elsewhere."""
    return os.environ.get("STATE_MACHINE_ARN")


def log_level() -> str:
    return os.environ.get("LOG_LEVEL", "INFO")


def require(value: str | None, name: str) -> str:
    """Fail fast and clearly when a Lambda-specific required var is unset."""
    if value is None:
        raise RuntimeError(f"{name} is not set")
    return value
