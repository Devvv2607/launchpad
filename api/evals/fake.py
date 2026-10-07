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

STRUCTURES = ["question-led", "story", "list", "offer-first", "dialogue", "one-liner"]
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

    def __init__(self, daily_quota_calls: int | None = None) -> None:
        super().__init__(max_retries=0)
        self.critiques: dict[str, int] = {}
        # Simulates a provider's daily limit running out after N calls (tests the eval's stop).
        self.daily_quota_calls = daily_quota_calls
        self.calls = 0

    async def _complete(self, model: str, messages: list[Message], **_: Any) -> RawCompletion:
        self.calls += 1
        if self.daily_quota_calls is not None and self.calls > self.daily_quota_calls:
            from launchpad.llm.errors import LLMRateLimitError

            raise LLMRateLimitError(
                "fake rate limit reached: tokens per day (TPD) limit exhausted",
                retry_after_s=2400,
            )
        system = messages[0].content
        if "planning step of a marketing assistant" in system:
            return _json(_fake_plan(messages[-1].content))
        if "You are Launchpad" in system:
            return _fake_agent_turn(system, messages)
        if "marketing planner" in system:
            return _json(_fake_calendar(system, messages[-1].content))
        label = re.search(r"## Channel: (.+)", system)
        content = CONTENT[label.group(1).strip()] if label else {}
        if "senior editor" in system:
            draft = messages[-1].content
            seen = self.critiques.get(draft, 0)
            self.critiques[draft] = seen + 1
            score = 7 if seen == 0 else 9
            reply: dict[str, Any] = {"scores": dict.fromkeys(("brand_voice", "clarity", "hook", "cta", "platform_fit"), score),
                     "issues": [] if score >= 8 else ["Sharpen the CTA"], "revised": content}  # fmt: skip
        else:
            n = int(re.search(r"Write (\d+) variant", messages[-1].content).group(1))  # type: ignore[union-attr]
            reply = {"variants": [
                {"angle": f"Angle {i}", "structure": STRUCTURES[i - 1], "hook": f"Distinct hook number {i} about topic {i * 7}",
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


def install_fake(daily_quota_calls: int | None = None) -> None:
    from launchpad.config import get_settings
    from launchpad.llm import service

    s = get_settings()
    s.llm_provider, s.llm_model, s.llm_fast_model = "gemini", "fake-writer", "fake-critic"
    s.embedding_provider, s.embedding_model = "gemini", "fake-embedding"
    if s.gemini_api_key is None:
        from pydantic import SecretStr

        s.gemini_api_key = SecretStr("fake")
    fake = FakeProvider(daily_quota_calls)
    service.llm._client_factory = lambda _provider: fake

    from launchpad.agent.research import Source, set_search_provider

    class _NoNetworkSearch:
        async def search(
            self, query: str, *, max_results: int = 5, recent: bool = True
        ) -> list[Source]:
            return [
                Source(
                    "Synthetic source (fake eval)", "https://example.com/fake-eval", "Synthetic."
                )
            ]

    set_search_provider(_NoNetworkSearch())


# ------------------------------------------------------------------ agent (scripted, offline)


def _json(obj: dict[str, Any]) -> RawCompletion:
    return RawCompletion(json.dumps(obj), [], Usage(400, 200), "fake")


def _request(text: str) -> str:
    """The latest user line of the planner's transcript, or the text itself."""
    lines = [ln[7:] for ln in text.splitlines() if ln.startswith("[user] ")]
    return (lines[-1] if lines else text).lower()


def _tools_for(request: str) -> list[str]:
    if "campaign" in request:
        return ["get_brand_context", "plan_campaign", "write_content", "build_email"]
    if "festival" in request or "trend" in request:
        return ["research_trends"]
    if "perform" in request or "numbers" in request:
        return ["get_analytics"]
    return ["get_brand_context"]


def _fake_plan(user_prompt: str) -> dict[str, Any]:
    req = _request(user_prompt)
    if "fake" in req and "review" in req:
        return {"intent": "harmful", "refusal": "I can't write fake reviews. I can help you ask real customers for reviews instead.", "goal": "", "steps": []}  # fmt: skip
    if "python" in req or "script" in req:
        return {"intent": "off_topic", "refusal": "That's outside marketing. I can help with content, campaigns and research.", "goal": "", "steps": []}  # fmt: skip
    steps = [{"title": f"Use {t}", "tool": t} for t in _tools_for(req)]
    return {"intent": "on_topic", "refusal": None, "goal": "Synthetic goal", "steps": [*steps, {"title": "Reply", "tool": "respond"}]}  # fmt: skip


def _fake_agent_turn(system: str, messages: list[Message]) -> RawCompletion:
    from datetime import date, timedelta

    from launchpad.llm.types import ToolCall

    last_user = max(i for i, m in enumerate(messages) if m.role == "user")
    request = messages[last_user].content.lower()
    done = [m for m in messages[last_user + 1 :] if m.role == "tool"]
    todo = _tools_for(request)
    if len(done) < len(todo):
        name = todo[len(done)]
        today = date.fromisoformat(re.search(r"Today is (\d{4}-\d{2}-\d{2})", system).group(1))  # type: ignore[union-attr]
        table: dict[str, dict[str, Any]] = {
            "get_brand_context": {"query": "voice, menu and offers"},
            "plan_campaign": {"goal": "sales", "brief": request, "start_date": str(today + timedelta(days=1)),
                              "end_date": str(today + timedelta(days=7)), "channels": ["instagram_post", "email"]},
            "write_content": {"channel": "instagram_post", "brief": request, "n_variants": 2},
            "build_email": {"brief": request},
            "research_trends": {"query": request, "days_ahead": 60},
            "get_analytics": {},
        }  # fmt: skip
        args = table[name]
        return RawCompletion(
            "", [ToolCall(f"call_{len(done)}", name, args)], Usage(400, 60), "fake"
        )
    results = " ".join(m.content for m in done)
    if "get_analytics" in todo:
        text = "There's no performance data yet: nothing is connected or published, so I won't guess numbers."
    elif "research_trends" in todo:
        fest = re.search(r'"name": "([^"]+)"', results)
        url = re.search(r'"url": "([^"]+)"', results)
        text = f"Worth planning for: {fest.group(1) if fest else 'no festivals in range'}." + (
            f" Trend context [1] {url.group(1)}" if url else ""
        )
    else:
        text = "Synthetic summary: drafts are ready for your review."
    return RawCompletion(text, [], Usage(400, 120), "fake")


def _fake_calendar(system: str, user: str) -> dict[str, Any]:
    from datetime import date, timedelta

    m = re.search(r"Dates: (\d{4}-\d{2}-\d{2}) \(\w+\) to (\d{4}-\d{2}-\d{2})", user)
    start, end = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))  # type: ignore[union-attr]
    channels = re.search(r"Use only these channels: (.+)\.", system).group(1).split(", ")  # type: ignore[union-attr]
    days = (end - start).days + 1
    items = [{"date": str(start + timedelta(days=i)), "channel": channels[i % len(channels)], "angle": f"Day {i + 1}",
              "cta": "Visit", "rationale": "Synthetic.", "observance": None} for i in range(days)]  # fmt: skip
    return {"summary": "Synthetic calendar.", "items": items}
