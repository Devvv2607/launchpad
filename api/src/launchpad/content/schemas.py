"""Structured outputs for the content engine.

Schemas define *structure*; numeric platform limits live in platform_rules and are checked
after generation (so a slightly-long draft is a fixable violation, not a parse failure).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model, model_validator

from launchpad.domain.enums import Channel


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class InstagramPostContent(_Strict):
    caption: str = Field(description="Full caption. Hook in the first line.")
    hashtags: list[str] = Field(description="Hashtags with leading #")
    cta: str = Field(description="The single call to action, as it appears in the caption")
    image_idea: str = Field(description="What the photo/visual should show. No text in the image.")
    alt_text: str = Field(description="Accessible description of the image")


class Slide(_Strict):
    headline: str
    body: str


class InstagramCarouselContent(_Strict):
    caption: str
    hashtags: list[str]
    slides: list[Slide] = Field(min_length=1, max_length=20)
    cta: str
    image_idea: str = Field(
        description="Visual style for the slide backgrounds. No text in images."
    )


class LinkedInPostContent(_Strict):
    text: str = Field(description="Post body. Hook before the 'see more' fold. Short paragraphs.")
    hashtags: list[str]
    cta: str


class XPostContent(_Strict):
    mode: Literal["single", "thread"]
    posts: list[str] = Field(min_length=1, max_length=10)
    hashtags: list[str]


class EmailSection(_Strict):
    type: Literal["hero", "text", "bullets", "quote", "cta"]
    heading: str | None = None
    body: str | None = None
    items: list[str] = Field(default_factory=list)
    button_label: str | None = None
    button_url: str | None = Field(
        default=None, description="https URL, or null to use the website"
    )


class EmailContent(_Strict):
    subject_variants: list[str] = Field(min_length=3, max_length=3)
    preheader: str
    sections: list[EmailSection] = Field(min_length=2, max_length=8)


CONTENT_MODELS: dict[Channel, type[BaseModel]] = {
    Channel.INSTAGRAM_POST: InstagramPostContent,
    Channel.INSTAGRAM_CAROUSEL: InstagramCarouselContent,
    Channel.LINKEDIN_POST: LinkedInPostContent,
    Channel.X_POST: XPostContent,
    Channel.EMAIL: EmailContent,
}

_WORDS = re.compile(r"[a-z0-9']+")


def _jaccard(a: str, b: str) -> float:
    wa, wb = set(_WORDS.findall(a.lower())), set(_WORDS.findall(b.lower()))
    return len(wa & wb) / len(wa | wb) if wa | wb else 1.0


class _DraftSetBase(_Strict):
    variants: list[Any]

    @model_validator(mode="after")
    def _distinct(self) -> _DraftSetBase:
        """Variants must take different angles, not paraphrase each other."""
        angles = [v.angle.strip().lower() for v in self.variants]
        if len(set(angles)) != len(angles):
            raise ValueError("Each variant needs a different angle label; two variants share one.")
        structures = [v.structure for v in self.variants]
        if len(set(structures)) != len(structures):
            raise ValueError(
                "Each variant needs a different structure (question-led, story, list, "
                "offer-first, dialogue, one-liner); two variants share one."
            )
        hooks = [v.hook for v in self.variants]
        for i in range(len(hooks)):
            for j in range(i + 1, len(hooks)):
                if _jaccard(hooks[i], hooks[j]) > 0.6:
                    raise ValueError(
                        f"Variants {i + 1} and {j + 1} open almost identically. "
                        "Rewrite one with a genuinely different hook and angle."
                    )
        return self


def draft_set_model(channel: Channel, n: int) -> type[_DraftSetBase]:
    content = CONTENT_MODELS[channel]
    variant = create_model(
        "Variant",
        __base__=_Strict,
        angle=(
            str,
            Field(description="2-5 word label for the creative angle, e.g. 'Rainy-day nostalgia'"),
        ),
        structure=(
            Literal["question-led", "story", "list", "offer-first", "dialogue", "one-liner"],
            Field(description="How the copy is built. Every variant uses a different one."),
        ),
        hook=(str, Field(description="The opening line that stops the scroll")),
        rationale=(
            str,
            Field(description="One sentence: why this angle suits the brief and audience"),
        ),
        content=(content, ...),
    )
    model: type[_DraftSetBase] = create_model(
        "DraftSet",
        __base__=_DraftSetBase,
        variants=(list[variant], Field(min_length=n, max_length=n)),
    )
    return model


class CritiqueScores(_Strict):
    brand_voice: int = Field(ge=1, le=10)
    clarity: int = Field(ge=1, le=10)
    hook: int = Field(ge=1, le=10)
    cta: int = Field(ge=1, le=10)
    platform_fit: int = Field(ge=1, le=10)

    def minimum(self) -> int:
        return min(self.brand_voice, self.clarity, self.hook, self.cta, self.platform_fit)

    def average(self) -> float:
        return round(
            (self.brand_voice + self.clarity + self.hook + self.cta + self.platform_fit) / 5, 1
        )


class _CritiqueBase(_Strict):
    scores: CritiqueScores
    issues: list[str] = Field(
        max_length=5, description="Up to 5 concrete, fixable problems, most important first."
    )
    revised: Any


def critique_model(channel: Channel) -> type[_CritiqueBase]:
    model: type[_CritiqueBase] = create_model(
        "Critique",
        __base__=_CritiqueBase,
        revised=(CONTENT_MODELS[channel], Field(description="Improved version fixing every issue")),
    )
    return model


class HashtagBuckets(_Strict):
    broad: list[str] = Field(max_length=10, description="High-volume tags for the category")
    niche: list[str] = Field(max_length=10, description="Specific to this post's topic/audience")
    branded: list[str] = Field(max_length=5, description="The business's own tags")
    local: list[str] = Field(max_length=8, description="City/neighbourhood tags")
