"""A scripted LLM for agent graph tests: answers the planner, the agent node and the content
engine's prompts, and records every call so tests can assert what the model saw."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from launchpad.llm.base import LLMClient
from launchpad.llm.types import Message, RawCompletion, ToolCall, Usage
from tests.content.fake_llm import critique
from tests.rag.fakes import hash_embed

AgentTurn = RawCompletion | Callable[[list[Message]], RawCompletion]


def kind_of(messages: list[Message]) -> str:
    system = messages[0].content if messages and messages[0].role == "system" else ""
    if "planning step of a marketing assistant" in system:
        return "planner"
    if "You are Launchpad" in system:
        return "agent"
    if "senior editor" in system:
        return "critique"
    if "copywriter" in system:
        return "write"
    if "marketing planner" in system:
        return "plan_campaign"
    if "social media strategist" in system:
        return "hashtags"
    return "other"


def plan(*steps: tuple[str, str], intent: str = "on_topic", refusal: str | None = None) -> str:
    return json.dumps(
        {
            "intent": intent,
            "refusal": refusal,
            "goal": "Help the business with its marketing" if intent == "on_topic" else "",
            "steps": [{"title": t, "tool": tool} for t, tool in steps],
        }
    )


def call(name: str, args: dict[str, Any], id_: str | None = None) -> ToolCall:
    return ToolCall(
        id=id_ or f"call_{name}_{abs(hash(json.dumps(args))) % 10_000}", name=name, arguments=args
    )


def tools(*calls: ToolCall, text: str = "") -> RawCompletion:
    return RawCompletion(text, list(calls), Usage(400, 60), "rid-agent")


def reply(text: str) -> RawCompletion:
    return RawCompletion(text, [], Usage(400, 120), "rid-agent")


def ig(angle: str, hook: str) -> dict[str, Any]:
    return {
        "angle": angle,
        "hook": hook,
        "rationale": f"{angle} fits the launch.",
        "content": {
            "caption": f"{hook}\nCold coffee is on the menu from Monday. Come try it.",
            "hashtags": ["#ColdCoffee", "#CafeLaunch", "#Bandra"],
            "cta": "Visit this week",
            "image_idea": "Glass of cold coffee with condensation on a wooden counter",
            "alt_text": "A glass of cold coffee on a café counter",
        },
    }


class AgentLLM(LLMClient):
    provider = "gemini"
    supports_embeddings = True

    def __init__(
        self,
        *,
        planner: str,
        turns: list[AgentTurn],
        variants: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(max_retries=0)
        self.planner = planner
        self.turns = list(turns)
        self.variants = variants or [
            ig("Launch-day hype", "Cold coffee season starts Monday"),
            ig("Behind the bar", "We tested 14 recipes to get this one right"),
        ]
        self.calls: list[tuple[str, list[Message]]] = []

    def of(self, kind: str) -> list[list[Message]]:
        return [m for k, m in self.calls if k == kind]

    async def _complete(self, model: str, messages: list[Message], **_: Any) -> RawCompletion:
        kind = kind_of(messages)
        self.calls.append((kind, messages))
        if kind == "planner":
            return RawCompletion(self.planner, [], Usage(800, 120), "rid-plan")
        if kind == "agent":
            if not self.turns:
                return reply("All done.")
            turn = self.turns.pop(0)
            return turn(messages) if callable(turn) else turn
        if kind == "write":
            m = re.search(r"Write (\d+) variant", messages[-1].content)
            n = int(m.group(1)) if m else len(self.variants)
            return RawCompletion(
                json.dumps({"variants": self.variants[: max(1, n)]}), [], Usage(600, 400), "rid-w"
            )
        if kind == "critique":
            draft = json.loads(
                messages[-1].content.split("Draft (JSON):\n", 1)[1].split("\n\nAutomated", 1)[0]
            )
            return RawCompletion(critique(9, draft), [], Usage(500, 300), "rid-c")
        raise AssertionError(f"unexpected prompt kind {kind!r}")

    async def _stream(
        self, model: str, messages: list[Message], **_: Any
    ) -> AsyncIterator[str | RawCompletion]:
        raise NotImplementedError
        yield ""  # pragma: no cover

    async def _embed(
        self, model: str, texts: list[str], *, task: str, dim: int
    ) -> list[list[float]]:
        return [hash_embed(t, dim) for t in texts]
