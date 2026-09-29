"""The Capabilities Engine: a registry every action goes through.

Each capability declares its contract up front -- input/output JSON
schemas, a safety tier, whether it's idempotent, and an owner -- and
`CapabilityRegistry.invoke` is the only way to run one. That single path is
where the guardrails live, so they apply to every capability and every
caller, without each one reimplementing them:

- the input is validated against the schema before the handler runs, and the
  output against its schema after (a handler that breaks its own contract
  fails loudly instead of feeding the model bad data);
- the caller states which safety tiers it may use, and anything outside
  them is refused (the agent loop can never reach `executes_action`);
- idempotent read-only capabilities get one retry with backoff, and nothing
  else is ever retried automatically;
- every attempt writes a trace span with input, output, status and latency.

See docs/decisions/ADR-0011 and docs/capabilities/ for the contracts.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from jsonschema import Draft202012Validator

from fleetalert.logging_config import alert_logger
from fleetalert.tracing import SpanKind, SpanStatus, Stopwatch, Tracer


class SafetyTier(StrEnum):
    READ_ONLY = "read_only"
    PROPOSES_ACTION = "proposes_action"
    EXECUTES_ACTION = "executes_action"


# What the agent loop may invoke on the model's behalf. `executes_action`
# is deliberately absent: nothing the model says can reach it.
AGENT_TIERS = frozenset({SafetyTier.READ_ONLY, SafetyTier.PROPOSES_ACTION})


@dataclass
class CapabilityContext:
    alert: dict[str, Any]
    machine: dict[str, Any] | None
    tracer: Tracer
    actor: str  # "agent", "system" or "human"
    parent_span_id: str | None = None


Handler = Callable[[dict[str, Any], CapabilityContext], dict[str, Any]]


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    safety_tier: SafetyTier
    idempotent: bool
    owner: str
    handler: Handler
    # Offered to the model as a tool. Separate from the tier because some
    # proposes_action capabilities (request_confirmation) are system-only.
    agent_callable: bool = False

    def __post_init__(self) -> None:
        Draft202012Validator.check_schema(self.input_schema)
        Draft202012Validator.check_schema(self.output_schema)
        if self.agent_callable and self.safety_tier == SafetyTier.EXECUTES_ACTION:
            raise ValueError(f"{self.name}: executes_action capabilities can never be agent-callable")

    @property
    def retries_on_failure(self) -> bool:
        return self.idempotent and self.safety_tier == SafetyTier.READ_ONLY


@dataclass(frozen=True)
class InvocationResult:
    ok: bool
    span_id: str
    attempts: int
    output: dict[str, Any] | None = None
    error: str | None = None
    # Exception class name when the handler raised, so a caller can tell a
    # guardrail refusal from an infrastructure failure.
    error_type: str | None = None

    def as_tool_content(self) -> dict[str, Any]:
        return self.output if self.ok and self.output is not None else {"error": self.error}


class CapabilityRegistry:
    def __init__(
        self,
        *,
        retry_backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._input_validators: dict[str, Draft202012Validator] = {}
        self._output_validators: dict[str, Draft202012Validator] = {}
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep

    def register(self, capability: Capability) -> None:
        if capability.name in self._capabilities:
            raise ValueError(f"Capability {capability.name!r} is already registered")
        self._capabilities[capability.name] = capability
        self._input_validators[capability.name] = Draft202012Validator(capability.input_schema)
        self._output_validators[capability.name] = Draft202012Validator(capability.output_schema)

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def all(self) -> list[Capability]:
        return list(self._capabilities.values())

    def agent_tools(self) -> list[dict[str, Any]]:
        """Tool definitions for the model, built from the registry.

        Deterministic order (registration order) so the prompt prefix stays
        cacheable.
        """
        return [
            {"name": c.name, "description": c.description, "input_schema": c.input_schema}
            for c in self._capabilities.values()
            if c.agent_callable
        ]

    def invoke(
        self,
        name: str,
        tool_input: Any,
        ctx: CapabilityContext,
        *,
        allowed_tiers: frozenset[SafetyTier],
    ) -> InvocationResult:
        log = alert_logger(__name__, ctx.tracer.alert_id)
        capability = self._capabilities.get(name)
        record_input = tool_input if isinstance(tool_input, dict) else {"raw": repr(tool_input)}

        def span(status: SpanStatus, *, output: dict[str, Any], latency_ms: float | None = None) -> str:
            return ctx.tracer.record(
                name=name,
                kind=SpanKind.CAPABILITY,
                actor=ctx.actor,
                status=status,
                input=record_input,
                output=output,
                parent_span_id=ctx.parent_span_id,
                latency_ms=latency_ms,
                attributes={
                    "safety_tier": str(capability.safety_tier) if capability else None,
                    "idempotent": capability.idempotent if capability else None,
                },
            )

        if capability is None:
            error = f"Unknown capability {name!r}. Available: {', '.join(self._capabilities)}"
            log.warning("capability refused: %s", error)
            return InvocationResult(ok=False, span_id=span(SpanStatus.FAILURE, output={"error": error}), attempts=0, error=error)

        if capability.safety_tier not in allowed_tiers or (
            ctx.actor == "agent" and not capability.agent_callable
        ):
            error = f"{name} ({capability.safety_tier}) is not permitted from this context"
            log.warning("capability denied: %s", error)
            return InvocationResult(ok=False, span_id=span(SpanStatus.DENIED, output={"error": error}), attempts=0, error=error)

        input_errors = sorted(
            self._input_validators[name].iter_errors(tool_input), key=lambda e: list(e.path)
        )
        if input_errors:
            details = [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in input_errors]
            error = f"Invalid input for {name}: {'; '.join(details)}. Call it again with valid input."
            log.warning("capability input rejected: %s", error)
            return InvocationResult(ok=False, span_id=span(SpanStatus.FAILURE, output={"error": error}), attempts=0, error=error)

        max_attempts = 2 if capability.retries_on_failure else 1
        for attempt in range(1, max_attempts + 1):
            watch = Stopwatch()
            try:
                output = capability.handler(tool_input, ctx)
            except Exception as exc:  # noqa: BLE001 -- any handler failure becomes a traced, structured error
                error = f"{name} failed: {type(exc).__name__}: {exc}"
                if attempt < max_attempts:
                    log.warning("capability attempt %d failed, retrying: %s", attempt, error)
                    span(SpanStatus.RETRY, output={"error": error, "attempt": attempt}, latency_ms=watch.elapsed_ms())
                    self._sleep(self._retry_backoff_seconds)
                    continue
                log.warning("capability failed after %d attempt(s): %s", attempt, error)
                span_id = span(SpanStatus.FAILURE, output={"error": error, "attempt": attempt}, latency_ms=watch.elapsed_ms())
                return InvocationResult(
                    ok=False, span_id=span_id, attempts=attempt, error=error, error_type=type(exc).__name__
                )

            output_errors = list(self._output_validators[name].iter_errors(output))
            if output_errors:
                # A contract bug in the handler, not a transient fault -- not retried.
                error = f"{name} broke its output contract: {output_errors[0].message}"
                log.error("%s", error)
                span_id = span(SpanStatus.FAILURE, output={"error": error}, latency_ms=watch.elapsed_ms())
                return InvocationResult(ok=False, span_id=span_id, attempts=attempt, error=error)

            span_id = span(SpanStatus.SUCCESS, output=output, latency_ms=watch.elapsed_ms())
            return InvocationResult(ok=True, span_id=span_id, attempts=attempt, output=output)

        raise AssertionError("unreachable")  # pragma: no cover
