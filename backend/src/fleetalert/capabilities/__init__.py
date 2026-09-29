"""The Capabilities Engine -- see registry.py."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import cache

from fleetalert.capabilities.builtin import BUILTIN_CAPABILITIES
from fleetalert.capabilities.registry import (
    AGENT_TIERS,
    Capability,
    CapabilityContext,
    CapabilityRegistry,
    InvocationResult,
    SafetyTier,
)

__all__ = [
    "AGENT_TIERS",
    "Capability",
    "CapabilityContext",
    "CapabilityRegistry",
    "InvocationResult",
    "SafetyTier",
    "build_registry",
    "default_registry",
]


def build_registry(
    *, retry_backoff_seconds: float = 0.5, sleep: Callable[[float], None] = time.sleep
) -> CapabilityRegistry:
    registry = CapabilityRegistry(retry_backoff_seconds=retry_backoff_seconds, sleep=sleep)
    for capability in BUILTIN_CAPABILITIES:
        registry.register(capability)
    return registry


@cache
def default_registry() -> CapabilityRegistry:
    return build_registry()
