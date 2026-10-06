from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

Role = Literal["system", "user", "assistant", "tool"]
# How hard a reasoning model should think. Only passed to models whose caps support it.
Reasoning = Literal["low", "medium", "high"]


class Purpose(StrEnum):
    """What a call is for. Workspaces can route each purpose to a different provider/model."""

    WRITING = "writing"
    CRITIQUE = "critique"
    PLANNING = "planning"
    EMBEDDING = "embedding"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    # Provider-specific data that must be echoed back verbatim on the next turn
    # (e.g. Gemini thought signatures).
    provider_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # role == "tool"
    name: str | None = None  # tool name for role == "tool"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens
        )


@dataclass
class RawCompletion:
    """What an adapter returns for one HTTP round-trip, before schema handling."""

    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    request_id: str | None
    finish_reason: str | None = None


@dataclass
class LLMResult(Generic[T]):
    text: str
    parsed: T | None
    tool_calls: list[ToolCall]
    provider: str
    model: str
    usage: Usage
    latency_ms: int
    cost_usd: Decimal | None  # None when the model's price is unknown
    request_id: str | None
    attempts: int = 1  # 2 when the structured-output repair retry was used
    finish_reason: str | None = None


@dataclass
class StreamDelta:
    text: str


@dataclass
class StreamDone:
    result: LLMResult[Any]


StreamEvent = StreamDelta | StreamDone
