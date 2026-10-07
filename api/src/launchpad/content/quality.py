"""Deterministic quality checks run after generation (and after every revision).

They return platform-rule-style `Violation`s. The ones in `MUST_FIX` send a draft back to the
critic for another round; whatever survives the review loop is saved on the draft and shown in
the UI. None of them block approval: a human can still decide a flagged draft is fine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from launchpad.content.facts import Fact, date_fact, extract_facts, unsupported
from launchpad.content.platform_rules import Violation
from launchpad.domain.enums import Channel

UNSUPPORTED_FACT = "unsupported_fact"
CAPTION_TOO_LONG = "caption_too_long"
TOO_MANY_FACTS = "too_many_facts"
LOGISTICS = "logistics_not_requested"
CRITIC_ADDED = "critic_added_facts"
TOO_SIMILAR = "too_similar"
MUST_FIX = {UNSUPPORTED_FACT, CAPTION_TOO_LONG, TOO_MANY_FACTS, LOGISTICS, CRITIC_ADDED}

CAPTION_WORD_TARGET = 60  # what the writer is asked for
CAPTION_WORD_LIMIT = 65  # what fails ("under ~60")
MAX_PRODUCT_FACTS = 3
OVERLAP_LIMIT = 0.6
INSTAGRAM = (Channel.INSTAGRAM_POST, Channel.INSTAGRAM_CAROUSEL)

LOGISTICS_TERMS = re.compile(
    r"\b(cod|cash on delivery|dispatch\w*|ships?\b|shipping|deliver\w*|exchange\w*|returns?|"
    r"refunds?)\b",
    re.I,
)
_HASHTAG = re.compile(r"#[\w-]+")
_WORD = re.compile(r"[\w'₹%-]+")


@dataclass
class Grounding:
    """Everything the writer was given. A fact in the output must come from here."""

    brief: str
    sources: list[Fact] = field(default_factory=list)
    brief_facts: set[str] = field(default_factory=set)  # facts the brief itself states
    brand_tags: set[str] = field(default_factory=set)  # e.g. {"#kadaktees"}

    @classmethod
    def build(
        cls,
        *,
        brief: str,
        texts: list[str],
        publish_date: date | None = None,
        business_name: str = "",
    ) -> Grounding:
        sources = [f for t in [brief, *texts] if t for f in extract_facts(t)]
        if publish_date is not None:
            sources.append(date_fact(publish_date))
        tag = "#" + re.sub(r"[^a-z0-9]", "", business_name.lower())
        return cls(
            brief=brief,
            sources=sources,
            brief_facts={f.key for f in extract_facts(brief)},
            brand_tags={tag} if len(tag) > 1 else set(),
        )


def copy_text(channel: Channel, content: dict[str, Any]) -> str:
    """All reader-facing words (not image ideas or alt text)."""
    parts: list[str] = []
    for key in ("caption", "text", "cta", "preheader"):
        if isinstance(content.get(key), str):
            parts.append(content[key])
    parts += [p for p in content.get("posts") or [] if isinstance(p, str)]
    parts += [s for s in content.get("subject_variants") or [] if isinstance(s, str)]
    for slide in content.get("slides") or []:
        parts += [str(slide.get("headline") or ""), str(slide.get("body") or "")]
    for sec in content.get("sections") or []:
        parts += [str(sec.get(k) or "") for k in ("heading", "body", "button_label")]
        parts += [str(i) for i in sec.get("items") or []]
    return "\n".join(p for p in parts if p)


def caption_words(caption: str) -> int:
    return len(_WORD.findall(_HASHTAG.sub(" ", caption)))


def product_facts(text: str, brief_facts: set[str]) -> list[Fact]:
    """Specs in a caption beyond the price and the facts the brief asked for."""
    seen: set[str] = set()
    out = []
    for f in extract_facts(text):
        if f.kind in ("price", "date", "range") or f.key in brief_facts or f.key in seen:
            continue
        seen.add(f.key)
        out.append(f)
    return out


def check(channel: Channel, content: dict[str, Any], g: Grounding | None) -> list[Violation]:
    if g is None:
        return []
    text = copy_text(channel, content)
    found = [
        Violation(
            UNSUPPORTED_FACT,
            "warning",
            f'"{f.text}" isn\'t in the brief, brand kit or campaign plan. '
            "Remove it or use a stated fact.",
        )
        for f in unsupported(text, g.sources)
    ]
    if channel in INSTAGRAM:
        caption = str(content.get("caption") or "")
        words = caption_words(caption)
        if words > CAPTION_WORD_LIMIT:
            found.append(
                Violation(
                    CAPTION_TOO_LONG,
                    "warning",
                    f"Caption is {words} words before hashtags; "
                    f"keep it under ~{CAPTION_WORD_TARGET}.",
                    "caption",
                )
            )
        specs = product_facts(caption, g.brief_facts)
        if len(specs) > MAX_PRODUCT_FACTS:
            found.append(
                Violation(
                    TOO_MANY_FACTS,
                    "warning",
                    f"Spec-dumping: {len(specs)} product facts "
                    f"({', '.join(f.text for f in specs)}). "
                    f"Keep the {MAX_PRODUCT_FACTS} that give one reason to care.",
                    "caption",
                )
            )
        if LOGISTICS_TERMS.search(caption) and not LOGISTICS_TERMS.search(g.brief):
            hit = LOGISTICS_TERMS.search(caption)
            assert hit is not None
            found.append(
                Violation(
                    LOGISTICS,
                    "warning",
                    f'Logistics ("{hit.group(0)}") weren\'t asked for in the brief; cut them.',
                    "caption",
                )
            )
    return found


def added_by_critic(
    channel: Channel, before: dict[str, Any], after: dict[str, Any], g: Grounding | None
) -> list[Violation]:
    """The critic may cut and reword, never add facts the draft didn't have."""
    if g is None:
        return []
    had = {f.key for f in extract_facts(copy_text(channel, before))} | g.brief_facts
    new = [
        f
        for f in extract_facts(copy_text(channel, after))
        if f.key not in had and f.kind != "range"
    ]
    if not new:
        return []
    listed = ", ".join(dict.fromkeys(f.text for f in new))
    return [
        Violation(
            CRITIC_ADDED,
            "warning",
            f"The revision added facts the draft didn't have: {listed}. Remove them.",
        )
    ]


@dataclass
class Draft:
    label: str
    angle: str
    content: dict[str, Any]


def _norm_words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def similarity_problems(
    channel: Channel, drafts: list[Draft], g: Grounding | None
) -> dict[str, str]:
    """For each later variant that repeats an earlier one, why. Compares angle, the facts used
    (beyond the brief's and the price) and the hashtags (beyond the brand's own)."""
    brief_facts = g.brief_facts if g else set()
    brand_tags = g.brand_tags if g else set()
    problems: dict[str, str] = {}
    for j, b in enumerate(drafts):
        for a in drafts[:j]:
            if a.label in problems:
                continue
            aw, bw = _norm_words(a.angle), _norm_words(b.angle)
            if aw and len(aw & bw) / len(aw | bw) >= 0.6:
                problems[b.label] = f'same angle as variant {a.label} ("{a.angle}")'
                break
            fa = {f.key for f in product_facts(copy_text(channel, a.content), brief_facts)}
            fb = {f.key for f in product_facts(copy_text(channel, b.content), brief_facts)}
            if min(len(fa), len(fb)) >= 2 and _overlap(fa, fb) > OVERLAP_LIMIT:
                problems[b.label] = f"uses mostly the same facts as variant {a.label}"
                break
            ta = {t.lower() for t in a.content.get("hashtags") or []} - brand_tags
            tb = {t.lower() for t in b.content.get("hashtags") or []} - brand_tags
            if min(len(ta), len(tb)) >= 2 and len(ta & tb) / len(ta | tb) > OVERLAP_LIMIT:
                problems[b.label] = f"repeats most of variant {a.label}'s hashtags"
                break
    return problems
