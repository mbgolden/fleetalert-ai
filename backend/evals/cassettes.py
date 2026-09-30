"""Record real Claude responses once, replay them for free on every PR.

A cassette holds the model's responses for one passing trial of a scenario,
round by round, plus a fingerprint of what the model was shown (model,
system prompt, tool definitions, opening user message). Replaying it runs
the real loop, capabilities and guardrails against those recorded
responses, so a code change that breaks a known-good trajectory (a renamed
tool, a tightened schema, a guardrail regression) fails CI without
spending anything.

If the fingerprint no longer matches, the prompt or tools changed and the
recording no longer says anything about how the model would behave; replay
reports the cassette as stale and the live tier is what counts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fleetalert.pricing import USAGE_FIELDS

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def fingerprint(request: dict[str, Any]) -> str:
    messages = request.get("messages") or []
    opening = messages[0]["content"] if messages else None
    material = {
        "model": request.get("model"),
        "system": request.get("system"),
        "tools": request.get("tools"),
        "opening_message": opening,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()[:16]


def serialize_response(response: Any) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for block in response.content:
        kind = getattr(block, "type", None)
        if kind == "text":
            blocks.append({"type": "text", "text": block.text})
        elif kind == "tool_use":
            blocks.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
    usage = getattr(response, "usage", None)
    return {
        "stop_reason": getattr(response, "stop_reason", None),
        "content": blocks,
        "usage": {f: int(getattr(usage, f, 0) or 0) for f in USAGE_FIELDS},
    }


def deserialize_response(data: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=data.get("stop_reason"),
        content=[SimpleNamespace(**block) for block in data["content"]],
        usage=SimpleNamespace(**data.get("usage", {})),
    )


@dataclass
class RecordedRound:
    fingerprint: str | None = None
    responses: list[dict[str, Any]] = field(default_factory=list)


class _RecordingMessages:
    def __init__(self, inner: Any, record: RecordedRound) -> None:
        self._inner = inner
        self._record = record

    def create(self, **kwargs: Any) -> Any:
        response = self._inner.messages.create(**kwargs)
        if self._record.fingerprint is None:
            self._record.fingerprint = fingerprint(kwargs)
        self._record.responses.append(serialize_response(response))
        return response


class RecordingClient:
    """Wraps a real anthropic client for one round and keeps its responses."""

    def __init__(self, inner: Any) -> None:
        self.recorded = RecordedRound()
        self.messages = _RecordingMessages(inner, self.recorded)


class ReplayExhausted(Exception):
    """The loop asked for more model calls than the recording holds, so the
    code under test took a different path than the recorded trajectory."""


class _ReplayMessages:
    def __init__(self, recorded: RecordedRound, client: ReplayClient) -> None:
        self._responses = iter(recorded.responses)
        self._expected = recorded.fingerprint
        self._client = client

    def create(self, **kwargs: Any) -> SimpleNamespace:
        if fingerprint(kwargs) != self._expected:
            self._client.stale = True
        try:
            return deserialize_response(next(self._responses))
        except StopIteration as exc:
            raise ReplayExhausted("recording ran out of model responses") from exc


class ReplayClient:
    def __init__(self, recorded: RecordedRound) -> None:
        self.stale = False
        self.messages = _ReplayMessages(recorded, self)


@dataclass
class Cassette:
    scenario_id: str
    model: str
    recorded_at: str
    rounds: list[RecordedRound]

    def path(self, directory: Path = CASSETTE_DIR) -> Path:
        return directory / f"{self.scenario_id}.json"

    def save(self, directory: Path = CASSETTE_DIR) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        data = {
            "scenario_id": self.scenario_id,
            "model": self.model,
            "recorded_at": self.recorded_at,
            "rounds": [{"fingerprint": r.fingerprint, "responses": r.responses} for r in self.rounds],
        }
        path = self.path(directory)
        path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    @classmethod
    def load(cls, scenario_id: str, directory: Path = CASSETTE_DIR) -> Cassette | None:
        path = directory / f"{scenario_id}.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text())
        return cls(
            scenario_id=data["scenario_id"],
            model=data["model"],
            recorded_at=data["recorded_at"],
            rounds=[RecordedRound(r["fingerprint"], r["responses"]) for r in data["rounds"]],
        )
