"""Deterministic fakes for RAG tests: a hashing bag-of-words embedder that behaves like a
real embedding model for similarity purposes (shared words -> higher cosine)."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import AsyncIterator
from typing import Any

from launchpad.llm.base import LLMClient
from launchpad.llm.types import Message, RawCompletion

_WORD = re.compile(r"[a-z0-9]+")
STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "is",
    "for",
    "on",
    "with",
    "our",
    "we",
    "at",
}


def hash_embed(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    for word in _WORD.findall(text.lower()):
        if word in STOP:
            continue
        h = int(hashlib.sha1(word.encode()).hexdigest(), 16)  # noqa: S324 - not security
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class FakeEmbedder(LLMClient):
    provider = "gemini"
    supports_embeddings = True

    def __init__(self, replies: list[str] | None = None) -> None:
        super().__init__(max_retries=0)
        self.replies = replies or []
        self.embedded: list[str] = []

    async def _embed(
        self, model: str, texts: list[str], *, task: str, dim: int
    ) -> list[list[float]]:
        self.embedded.extend(texts)
        return [hash_embed(t, dim) for t in texts]

    async def _complete(self, model: str, messages: list[Message], **_: Any) -> RawCompletion:
        from launchpad.llm.types import Usage

        return RawCompletion(self.replies.pop(0), [], Usage(10, 10), "rid")

    async def _stream(
        self, model: str, messages: list[Message], **_: Any
    ) -> AsyncIterator[str | RawCompletion]:
        raise NotImplementedError
        yield ""  # pragma: no cover
