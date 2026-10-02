"""A scripted LLM that answers based on which prompt it receives."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from launchpad.llm.base import LLMClient
from launchpad.llm.errors import LLMError
from launchpad.llm.types import Message, RawCompletion, Usage
from tests.rag.fakes import hash_embed

Script = Callable[[str, str], str | LLMError]  # (kind, user_prompt) -> raw JSON reply or error


def kind_of(messages: list[Message]) -> str:
    system = messages[0].content if messages and messages[0].role == "system" else ""
    if "senior editor" in system:
        return "critique"
    if "copywriter" in system:
        return "write"
    if "social media strategist" in system:
        return "hashtags"
    if "brand strategist" in system:
        return "voice"
    return "other"


class ScriptedLLM(LLMClient):
    provider = "gemini"
    supports_embeddings = True

    def __init__(self, script: Script) -> None:
        super().__init__(max_retries=0)
        self.script = script
        self.calls: list[tuple[str, list[Message]]] = []

    async def _complete(self, model: str, messages: list[Message], **_: Any) -> RawCompletion:
        kind = kind_of(messages)
        # Repair turns append [assistant, user]; the "kind" comes from the original system prompt.
        self.calls.append((kind, messages))
        reply = self.script(kind, messages[-1].content)
        if isinstance(reply, LLMError):
            raise reply
        return RawCompletion(reply, [], Usage(500, 300), f"rid-{len(self.calls)}")

    async def _stream(
        self, model: str, messages: list[Message], **_: Any
    ) -> AsyncIterator[str | RawCompletion]:
        raise NotImplementedError
        yield ""  # pragma: no cover

    async def _embed(
        self, model: str, texts: list[str], *, task: str, dim: int
    ) -> list[list[float]]:
        return [hash_embed(t, dim) for t in texts]


def ig_variant(
    angle: str, hook: str, caption: str | None = None, tags: list[str] | None = None
) -> dict[str, Any]:
    return {
        "angle": angle,
        "hook": hook,
        "rationale": f"{angle} suits monsoon regulars.",
        "content": {
            "caption": caption or f"{hook}\nMasala chai and pakoras all week. Drop in after work.",
            "hashtags": tags if tags is not None else ["#MumbaiRains", "#chai", "#Bandra"],
            "cta": "Drop in after work",
            "image_idea": "Steaming kulhad of chai on a rain-streaked window ledge",
            "alt_text": "A cup of masala chai by a rainy window",
        },
    }


def drafts(*variants: dict[str, Any]) -> str:
    return json.dumps({"variants": list(variants)})


THREE = drafts(
    ig_variant("Rainy-day nostalgia", "Remember chai breaks at school when it poured?"),
    ig_variant("Offer-led", "Monsoon menu is here: masala chai with pakoras"),
    ig_variant("Behind the counter", "Our chaiwala starts the charcoal at 6am"),
)


def critique(score: int, revised: dict[str, Any], issues: list[str] | None = None) -> str:
    return json.dumps(
        {
            "scores": {
                "brand_voice": score,
                "clarity": score,
                "hook": score,
                "cta": score,
                "platform_fit": score,
            },
            "issues": issues if issues is not None else ([] if score >= 8 else ["CTA is vague"]),
            "revised": revised,
        }
    )
