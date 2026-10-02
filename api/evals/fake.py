"""Scripted provider for `python -m evals.run --fake`: proves the harness end-to-end in CI
without API keys. Output is obviously synthetic; fake reports are labelled as such."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import AsyncIterator
from typing import Any

from launchpad.llm.base import LLMClient
from launchpad.llm.types import Message, RawCompletion, Usage

_WORD = re.compile(r"[a-z0-9]+")

CONTENT: dict[str, dict[str, Any]] = {
    "Instagram post": {
        "caption": "Synthetic caption for the harness.\nCome by this week.",
        "hashtags": ["#one", "#two", "#three"], "cta": "Come by", "image_idea": "A cup", "alt_text": "A cup",
    },
    "Instagram carousel": {
        "caption": "Swipe through.", "hashtags": ["#one", "#two", "#three"], "cta": "Visit",
        "image_idea": "Flat colour", "slides": [{"headline": f"Point {i}", "body": "Detail."} for i in range(1, 7)],
    },
    "LinkedIn post": {"text": "A synthetic insight.\n\nShort paragraph.", "hashtags": ["#a", "#b", "#c"], "cta": "Reply"},
    "X post": {"mode": "single", "posts": ["Synthetic post."], "hashtags": []},
    "Email": {
        "subject_variants": ["Subject one", "Subject two", "Subject three"],
        "preheader": "A synthetic preheader long enough for the rule to pass.",
        "sections": [
            {"type": "hero", "heading": "Hello", "body": "Body", "items": [], "button_label": None, "button_url": None},
            {"type": "cta", "heading": None, "body": None, "items": [], "button_label": "Go", "button_url": None},
        ],
    },
}  # fmt: skip


class FakeProvider(LLMClient):
    provider = "gemini"
    supports_embeddings = True

    def __init__(self) -> None:
        super().__init__(max_retries=0)
        self.critiques: dict[str, int] = {}

    async def _complete(self, model: str, messages: list[Message], **_: Any) -> RawCompletion:
        system = messages[0].content
        label = re.search(r"## Channel: (.+)", system)
        content = CONTENT[label.group(1).strip()] if label else {}
        if "senior editor" in system:
            draft = messages[-1].content
            seen = self.critiques.get(draft, 0)
            self.critiques[draft] = seen + 1
            score = 7 if seen == 0 else 9
            reply = {"scores": dict.fromkeys(("brand_voice", "clarity", "hook", "cta", "platform_fit"), score),
                     "issues": [] if score >= 8 else ["Sharpen the CTA"], "revised": content}  # fmt: skip
        else:
            n = int(re.search(r"Write (\d+) variant", messages[-1].content).group(1))  # type: ignore[union-attr]
            reply = {"variants": [
                {"angle": f"Angle {i}", "hook": f"Distinct hook number {i} about topic {i * 7}",
                 "rationale": "Synthetic.", "content": content} for i in range(1, n + 1)]}  # fmt: skip
        return RawCompletion(json.dumps(reply), [], Usage(400, 200), "fake")

    async def _stream(
        self, model: str, messages: list[Message], **_: Any
    ) -> AsyncIterator[str | RawCompletion]:
        raise NotImplementedError
        yield ""  # pragma: no cover

    async def _embed(
        self, model: str, texts: list[str], *, task: str, dim: int
    ) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * dim
            for w in _WORD.findall(t.lower()):
                v[int(hashlib.sha1(w.encode()).hexdigest(), 16) % dim] += 1  # noqa: S324
            n = math.sqrt(sum(x * x for x in v)) or 1
            out.append([x / n for x in v])
        return out


def install_fake() -> None:
    from launchpad.config import get_settings
    from launchpad.llm import service

    s = get_settings()
    s.llm_provider, s.llm_model, s.llm_fast_model = "gemini", "fake-writer", "fake-critic"
    s.embedding_provider, s.embedding_model = "gemini", "fake-embedding"
    if s.gemini_api_key is None:
        from pydantic import SecretStr

        s.gemini_api_key = SecretStr("fake")
    fake = FakeProvider()
    service.llm._client_factory = lambda _provider: fake
