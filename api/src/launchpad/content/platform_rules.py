"""Platform rules, in one place, enforced *after* generation.

Hard rules ("error") are platform limits: the content cannot be published as-is. They are
fed back into the critique/revise loop; if they survive it, the draft is flagged and the
UI blocks approval until a human fixes it. We never truncate silently.
Soft rules ("warning") are platform norms; they're shown, not enforced.

Limits checked 2026-10-02 against public platform guidance:
  Instagram  2,200-char captions, feed truncates ~125 chars, 30 hashtags max (3-5 advised),
             carousels up to 20 slides (we generate 5-10), links in captions aren't clickable.
  LinkedIn   3,000 chars, "see more" fold ~210 chars desktop / ~140 mobile.
  X          280 weighted chars on free accounts (URLs count 23, emoji/CJK count 2).
  Email      subject <= ~60 chars shows fully in most clients; preheader 40-130 chars.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from launchpad.domain.enums import Channel

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Violation:
    rule: str
    severity: Severity
    message: str
    field: str = ""


@dataclass(frozen=True)
class ChannelRules:
    label: str
    max_chars: int | None = None
    fold_chars: int | None = None  # where the feed cuts to "…more"
    hashtags_max: int = 0
    hashtags_recommended: tuple[int, int] = (0, 0)
    links_clickable: bool = True
    notes: str = ""


RULES: dict[Channel, ChannelRules] = {
    Channel.INSTAGRAM_POST: ChannelRules(
        "Instagram post", 2200, 125, 30, (3, 5), links_clickable=False,
        notes="Hook in the first 125 characters. Links aren't clickable: say 'link in bio'.",
    ),
    Channel.INSTAGRAM_CAROUSEL: ChannelRules(
        "Instagram carousel", 2200, 125, 30, (3, 5), links_clickable=False,
        notes="5-10 slides. Slide 1 is the hook; the last slide carries the CTA.",
    ),
    Channel.LINKEDIN_POST: ChannelRules(
        "LinkedIn post", 3000, 210, 5, (3, 5),
        notes="Hook before the ~210-char 'see more' fold (~140 on mobile). Short paragraphs.",
    ),
    Channel.X_POST: ChannelRules(
        "X post", 280, None, 2, (0, 2),
        notes="Each post max 280 weighted characters; threads of 2-10 posts.",
    ),
    Channel.EMAIL: ChannelRules(
        "Email", None, None, 0, (0, 0),
        notes="Subject <= 60 chars, preheader 40-130 chars, one clear CTA.",
    ),
    Channel.POSTER: ChannelRules("Poster", None, None, 0, (0, 0)),
}  # fmt: skip

CAROUSEL_SLIDES = (5, 10)
SLIDE_HEADLINE_MAX = 60
SLIDE_BODY_MAX = 220
THREAD_POSTS = (2, 10)
EMAIL_SUBJECT_MAX = 60
EMAIL_SUBJECT_HARD_MAX = 100
EMAIL_PREHEADER = (40, 130)


def _tag_char(ch: str) -> bool:
    # Letters, numbers, combining marks (Devanagari vowel signs etc.) and underscore.
    return ch == "_" or unicodedata.category(ch)[0] in ("L", "N", "M")


def is_valid_hashtag(tag: str) -> bool:
    body = tag[1:]
    return (
        tag.startswith("#")
        and 0 < len(body) <= 100
        and unicodedata.category(body[0])[0] in ("L", "N")
        and all(_tag_char(ch) for ch in body)
    )


URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
BANNED_HASHTAGS = {
    "#followforfollow", "#follow4follow", "#f4f", "#like4like", "#l4l", "#likeforlike",
    "#tagsforlikes", "#followback", "#instalike", "#spam",
}  # fmt: skip


def x_weighted_length(text: str) -> int:
    """Approximation of X's weighted counting: URLs = 23; most Latin/punctuation = 1;
    emoji, CJK and other wide characters = 2."""
    length = 0
    last = 0
    for m in URL_RE.finditer(text):
        length += _weigh(text[last : m.start()]) + 23
        last = m.end()
    return length + _weigh(text[last:])


def _weigh(s: str) -> int:
    total = 0
    for ch in s:
        cp = ord(ch)
        light = (
            cp <= 0x10FF  # Latin, Greek, Cyrillic, Hebrew, Arabic, Devanagari ... Georgian
            or 0x2000 <= cp <= 0x200D
            or 0x2010 <= cp <= 0x201F
            or 0x2032 <= cp <= 0x2037
        )
        total += 1 if light and unicodedata.category(ch) != "So" else 2
    return total


def normalize_hashtags(tags: list[str]) -> list[str]:
    """Deterministic clean-up (format, dedupe). Doesn't invent or reorder by guesswork."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        body = "".join(ch for ch in raw.strip().lstrip("#") if _tag_char(ch))
        tag = "#" + body
        if not is_valid_hashtag(tag) or tag.lower() in BANNED_HASHTAGS:
            continue
        if tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def _len_check(rules: list[Violation], text: str, limit: int, field: str, label: str) -> None:
    if len(text) > limit:
        rules.append(
            Violation(
                "max_chars",
                "error",
                f"{label} is {len(text)} characters; the limit is {limit}.",
                field,
            )
        )


def validate(channel: Channel, content: dict[str, Any]) -> list[Violation]:
    """Validate structured channel content (see content.schemas)."""
    r = RULES[channel]
    out: list[Violation] = []
    tags = content.get("hashtags") or []

    if channel in (Channel.INSTAGRAM_POST, Channel.INSTAGRAM_CAROUSEL, Channel.LINKEDIN_POST):
        text = content.get("caption") or content.get("text") or ""
        full = text + ("\n\n" + " ".join(tags) if tags else "")
        assert r.max_chars is not None
        _len_check(out, full, r.max_chars, "caption", f"{r.label} text incl. hashtags")
        if r.fold_chars and len(text) > r.fold_chars:
            first_break = text.find("\n")
            hook = text[: first_break if 0 < first_break <= r.fold_chars else r.fold_chars]
            if len(hook.strip()) < 20:
                out.append(
                    Violation(
                        "hook_before_fold",
                        "warning",
                        f"Put a hook in the first {r.fold_chars} characters (before '…more').",
                        "caption",
                    )
                )
        if not r.links_clickable and URL_RE.search(text):
            out.append(
                Violation(
                    "no_links",
                    "warning",
                    "Links aren't clickable in Instagram captions; say 'link in bio' instead.",
                    "caption",
                )
            )

    if channel == Channel.INSTAGRAM_CAROUSEL:
        slides = content.get("slides") or []
        lo, hi = CAROUSEL_SLIDES
        if not lo <= len(slides) <= hi:
            out.append(
                Violation(
                    "slide_count",
                    "error",
                    f"Carousels need {lo}-{hi} slides; got {len(slides)}.",
                    "slides",
                )
            )
        for i, s in enumerate(slides, 1):
            _len_check(
                out,
                s.get("headline", ""),
                SLIDE_HEADLINE_MAX,
                f"slides.{i}.headline",
                f"Slide {i} headline",
            )
            _len_check(
                out, s.get("body", ""), SLIDE_BODY_MAX, f"slides.{i}.body", f"Slide {i} body"
            )

    if channel == Channel.X_POST:
        posts = content.get("posts") or []
        if content.get("mode") == "thread":
            lo, hi = THREAD_POSTS
            if not lo <= len(posts) <= hi:
                out.append(
                    Violation(
                        "thread_length",
                        "error",
                        f"Threads need {lo}-{hi} posts; got {len(posts)}.",
                        "posts",
                    )
                )
        elif len(posts) != 1:
            out.append(
                Violation(
                    "single_post", "error", "A single X post must have exactly one post.", "posts"
                )
            )
        for i, p in enumerate(posts, 1):
            text = p + (" " + " ".join(tags) if i == len(posts) and tags else "")
            n = x_weighted_length(text)
            if n > 280:
                out.append(
                    Violation(
                        "max_chars",
                        "error",
                        f"Post {i} is {n}/280 weighted characters.",
                        f"posts.{i}",
                    )
                )

    if channel == Channel.EMAIL:
        for i, subject in enumerate(content.get("subject_variants") or [], 1):
            if len(subject) > EMAIL_SUBJECT_HARD_MAX:
                out.append(
                    Violation(
                        "subject_length",
                        "error",
                        f"Subject {i} is {len(subject)} characters (max {EMAIL_SUBJECT_HARD_MAX}).",
                        f"subject_variants.{i}",
                    )
                )
            elif len(subject) > EMAIL_SUBJECT_MAX:
                out.append(
                    Violation(
                        "subject_length",
                        "warning",
                        f"Subject {i} is {len(subject)} characters; over {EMAIL_SUBJECT_MAX} gets cut off on mobile.",
                        f"subject_variants.{i}",
                    )
                )
        pre = content.get("preheader") or ""
        lo, hi = EMAIL_PREHEADER
        if not lo <= len(pre) <= hi:
            out.append(
                Violation(
                    "preheader_length",
                    "warning",
                    f"Preheader is {len(pre)} characters; aim for {lo}-{hi}.",
                    "preheader",
                )
            )
        ctas = [s for s in content.get("sections") or [] if s.get("type") == "cta"]
        if not ctas:
            out.append(
                Violation(
                    "cta_missing", "error", "The email needs a call-to-action button.", "sections"
                )
            )

    if r.hashtags_max or tags:
        if len(tags) > r.hashtags_max:
            out.append(
                Violation(
                    "hashtag_count",
                    "error",
                    f"{len(tags)} hashtags; {r.label} allows at most {r.hashtags_max}.",
                    "hashtags",
                )
            )
        lo, hi = r.hashtags_recommended
        if hi and not lo <= len(tags) <= hi and len(tags) <= r.hashtags_max:
            out.append(
                Violation(
                    "hashtag_count",
                    "warning",
                    f"{len(tags)} hashtags; {lo}-{hi} works best on {r.label}.",
                    "hashtags",
                )
            )
        bad = [t for t in tags if not is_valid_hashtag(t) or t.lower() in BANNED_HASHTAGS]
        if bad:
            out.append(
                Violation(
                    "hashtag_format",
                    "error",
                    f"Invalid or banned hashtags: {', '.join(bad)}.",
                    "hashtags",
                )
            )
    return out


def has_errors(violations: list[Violation]) -> bool:
    return any(v.severity == "error" for v in violations)
