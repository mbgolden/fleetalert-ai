"""A minimal stand-in for the anthropic SDK client, for loop tests.

Only implements the surface fleetalert.agent.loop actually calls
(`client.messages.create(...)` returning something with a `.content` list
of blocks that have `.type`/`.name`/`.input`/`.id` or `.type`/`.text`) --
tests never hit the real Claude API.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def tool_use_block(name: str, tool_input: dict[str, Any], block_id: str = "toolu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def text_block(text: str = "thinking...") -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


class _FakeMessages:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = iter(responses)

    def create(self, **_kwargs: Any) -> SimpleNamespace:
        try:
            return next(self._responses)
        except StopIteration as exc:
            raise AssertionError("FakeClient ran out of scripted responses") from exc


class FakeAnthropicClient:
    """responses: one SimpleNamespace(content=[...]) per expected loop turn."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.messages = _FakeMessages(responses)


def response(*blocks: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks))
