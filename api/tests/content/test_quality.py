"""Post-generation quality rules: grounding, spec-dumping, logistics, critic-added facts,
variant diversity, and how the engine acts on them."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select

from launchpad.agent.research import build_query, usable
from launchpad.content import quality
from launchpad.content.engine import write_content
from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import Channel
from launchpad.llm.types import Message, RawCompletion
from launchpad.models import LLMCall, Workspace
from tests.content.fake_llm import ScriptedLLM, critique, draft_in, drafts, ig_variant
from tests.content.test_engine import _ws, env, use  # noqa: F401  (env is a fixture)

pytestmark = pytest.mark.usefixtures("env")
BRIEF = "Monsoon drop: 5 rain-themed graphic tees, ₹699 each"
DOC = (
    "Graphic tees: 100% combed cotton, 220 GSM. Price: ₹699 per tee; bundles of 3 for ₹1,899. "
    "Free shipping on orders above ₹999; cash on delivery. Ships within 48 hours. 7-day size "
    "exchange. Drops of 4 to 6 tees; each design is printed in a limited batch of 150."
)
IG = Channel.INSTAGRAM_POST
EMAIL_VARIANT: dict[str, Any] = {
    "angle": "Early access",
    "structure": "offer-first",
    "hook": "You're early",
    "rationale": "Subscribers get first pick.",
    "content": {
        "subject_variants": ["You're early", "Monsoon drop, first look", "5 tees, ₹699 each"],
        "preheader": "Subscribers get first pick of the monsoon drop before it goes live.",
        "sections": [
            {"type": "hero", "heading": "Monsoon drop", "body": "5 rain-themed tees, ₹699 each.",
             "items": [], "button_label": None, "button_url": None},
            {"type": "cta", "heading": None, "body": None, "items": [],
             "button_label": "Get first pick", "button_url": None},
        ],
    },
}  # fmt: skip


def g(publish: date | None = None) -> quality.Grounding:
    return quality.Grounding.build(
        brief=BRIEF, texts=[DOC], publish_date=publish, business_name="Kadak Tees"
    )


def rules(content: dict[str, Any], grounding: quality.Grounding) -> list[str]:
    return [v.rule for v in quality.check(IG, content, grounding)]


def test_a_tight_grounded_caption_passes() -> None:
    caption = "Monsoon, but make it wearable. 5 rain-themed tees, ₹699 each. Link in bio."
    assert rules({"caption": caption, "hashtags": ["#KadakTees"]}, g()) == []


def test_spec_dump_logistics_length_and_invented_facts_are_flagged() -> None:
    caption = (
        "Barish ka beat, tee ke seat! 4 designs, 5 rain-themed tees, ₹699 each. 100% combed "
        "cotton, 220 GSM, limited batch of 150. Free shipping over ₹999, COD, ships within 48 "
        "hrs, 7-day exchange. " + "Ekdum kadak vibes all monsoon long. " * 9
    )
    found = rules({"caption": caption}, g())
    assert quality.UNSUPPORTED_FACT in found  # "4 designs"
    assert quality.TOO_MANY_FACTS in found
    assert quality.LOGISTICS in found
    assert quality.CAPTION_TOO_LONG in found


def test_logistics_are_fine_when_the_brief_asks() -> None:
    grounding = quality.Grounding.build(brief=BRIEF + ", mention COD", texts=[DOC])
    assert quality.LOGISTICS not in rules({"caption": "₹699 each. COD available."}, grounding)


def test_wrong_date_is_unsupported_and_the_planned_date_is_fine() -> None:
    planned = g(date(2026, 10, 10))
    assert rules({"caption": "Live from Oct 12! ₹699 each."}, planned) == [quality.UNSUPPORTED_FACT]
    assert rules({"caption": "Live from 10 Oct! ₹699 each."}, planned) == []


def test_critic_may_not_add_facts() -> None:
    before = {"caption": "Rain-ready tees, ₹699 each."}
    after = {"caption": "Rain-ready tees, ₹699 each. 220 GSM cotton."}
    assert [v.rule for v in quality.added_by_critic(IG, before, after, g())] == [
        quality.CRITIC_ADDED
    ]
    assert quality.added_by_critic(IG, before, {"caption": "Rain-ready, ₹699."}, g()) == []


def test_similarity_by_angle_facts_and_hashtags() -> None:
    def d(label: str, angle: str, caption: str, tags: list[str]) -> quality.Draft:
        return quality.Draft(label, angle, {"caption": caption, "hashtags": tags})

    same_angle = [
        d("A", "Rainy day nostalgia", "x", ["#a"]),
        d("B", "Rainy-day nostalgia", "y", ["#b"]),
    ]
    assert "same angle" in quality.similarity_problems(IG, same_angle, g())["B"]
    same_facts = [
        d("A", "Fabric", "220 GSM, batch of 150, 48 hrs", ["#a"]),
        d("B", "Quality", "220 GSM and 150 pieces only, 48 hrs", ["#b"]),
    ]
    assert "same facts" in quality.similarity_problems(IG, same_facts, g())["B"]
    same_tags = [
        d("A", "Story", "x", ["#KadakTees", "#Monsoon", "#Streetwear", "#Mumbai"]),
        d("B", "Offer", "y", ["#kadaktees", "#Monsoon", "#Streetwear", "#Mumbai"]),
    ]
    assert "hashtags" in quality.similarity_problems(IG, same_tags, g())["B"]
    distinct = [
        d("A", "Story", "x", ["#KadakTees", "#A1", "#A2"]),
        d("B", "Offer", "y", ["#KadakTees", "#B1", "#B2"]),
    ]
    assert quality.similarity_problems(IG, distinct, g()) == {}


def test_research_filters_and_anchored_query() -> None:
    assert not usable("https://nsearchives.nseindia.com/x/FP_22SEP2026.pdf", 0.9, 0.5)
    assert not usable("https://www.facebook.com/brand/posts/1", 0.9, 0.5)
    assert not usable("https://example.in/a", 0.3, 0.5)
    assert usable("https://example.in/monsoon-fashion", 0.7, 0.5)
    q = build_query("monsoon streetwear trends", brand="Kadak Tees", category="fashion",
                    city="Mumbai", today=date(2026, 10, 7))  # fmt: skip
    assert q == "monsoon streetwear trends Kadak Tees fashion Mumbai October 2026"


# ------------------------------------------------------------------ engine behaviour


async def test_unsupported_fact_is_revised_then_flagged_if_it_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = ig_variant("Launch", "Drop day", caption="4 designs, ₹699 each. Link in bio.")
    prompts: list[str] = []

    def script(kind: str, prompt: str) -> str:
        if kind == "write":
            return drafts(bad)
        prompts.append(prompt)
        return critique(9, draft_in(prompt))  # a stubborn critic that changes nothing

    use(monkeypatch, ScriptedLLM(script))
    ws, ctx = await _ws()
    async with get_sessionmaker()() as db:
        ws = await db.get(Workspace, ws.id)
        assert ws is not None
        [v] = await write_content(db, ws, ctx, channel=IG, brief=BRIEF, n_variants=1, save=False)
    assert '"4 designs"' in prompts[0]  # the critic is told exactly which fact is unsupported
    assert len(v.iterations) == 3  # high scores, but the must-fix forced both revision rounds
    assert quality.UNSUPPORTED_FACT in [x["rule"] for x in v.violations]  # flagged, not hidden
    assert not v.blocked  # a human can still decide


async def test_duplicate_variant_is_regenerated_once(monkeypatch: pytest.MonkeyPatch) -> None:
    tags = ["#KadakTees", "#Monsoon", "#Streetwear", "#Mumbai"]
    a = ig_variant("Rainy day", "Rain again?", caption="Rain again? ₹699 each.", tags=tags)
    b = ig_variant("Offer first", "₹699, five tees", caption="₹699 each, five tees.", tags=tags)
    fresh = ig_variant("Behind the ink", "Drawn in Andheri", caption="Drawn in Andheri. ₹699.",
                       tags=["#KadakTees", "#DrawnInMumbai", "#InkLife"])  # fmt: skip
    writes: list[str] = []

    def script(kind: str, prompt: str) -> str:
        if kind == "write":
            writes.append(prompt)
            return (
                drafts(a, b)
                if len(writes) == 1
                else json.dumps({"variants": [{**fresh, "structure": "story"}]})
            )
        return critique(9, draft_in(prompt))

    use(monkeypatch, ScriptedLLM(script))
    ws, ctx = await _ws()
    async with get_sessionmaker()() as db:
        ws = await db.get(Workspace, ws.id)
        assert ws is not None
        out = await write_content(db, ws, ctx, channel=IG, brief=BRIEF, n_variants=2, save=False)
    assert len(writes) == 2 and "different hashtags" in writes[1]
    assert [v.angle for v in out] == ["Rainy day", "Behind the ink"]
    assert not any(x["rule"] == quality.TOO_SIMILAR for v in out for x in v.violations)


async def test_email_review_uses_the_main_model(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str]] = []

    class Spy(ScriptedLLM):
        async def _complete(self, model: str, messages: list[Message], **kw: Any) -> RawCompletion:
            seen.append((model, messages[0].content[:40]))
            return await super()._complete(model, messages, **kw)

    def script(kind: str, prompt: str) -> str:
        if kind == "write":
            return json.dumps({"variants": [EMAIL_VARIANT]})
        return critique(9, EMAIL_VARIANT["content"])

    use(monkeypatch, Spy(script))
    ws, ctx = await _ws()
    async with get_sessionmaker()() as db:
        ws = await db.get(Workspace, ws.id)
        assert ws is not None
        await write_content(db, ws, ctx, channel=Channel.EMAIL, brief="Monsoon newsletter",
                            n_variants=1, save=False)  # fmt: skip
        reviews = list(
            await db.scalars(select(LLMCall).where(LLMCall.purpose == "critique_content"))
        )
    assert reviews and all(r.model == "gemini-3.6-flash" for r in reviews)  # not the fast model


def test_critique_issues_are_capped_at_five() -> None:
    from pydantic import ValidationError

    from launchpad.content.schemas import critique_model

    model = critique_model(IG)
    payload = json.loads(critique(6, {"caption": "x", "hashtags": [], "cta": "go",
                                      "image_idea": "i", "alt_text": "a"}))  # fmt: skip
    payload["issues"] = [f"issue {i}" for i in range(6)]
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    payload["issues"] = payload["issues"][:5]
    model.model_validate(payload)
