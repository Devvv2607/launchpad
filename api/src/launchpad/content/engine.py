"""Content engine: write → validate → critique/revise (≤2 rounds) → save drafts.

These are plain services; the Phase 3 agent wraps them as tools. Progress is reported via an
optional async callback so the API can stream it over SSE.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.content.context import BrandContext, build_brand_context
from launchpad.content.email_render import render_email
from launchpad.content.platform_rules import (
    CAROUSEL_SLIDES,
    EMAIL_PREHEADER,
    EMAIL_SUBJECT_MAX,
    RULES,
    SLIDE_BODY_MAX,
    SLIDE_HEADLINE_MAX,
    THREAD_POSTS,
    normalize_hashtags,
    validate,
)
from launchpad.content.schemas import (
    CONTENT_MODELS,
    CritiqueScores,
    EmailContent,
    HashtagBuckets,
    critique_model,
    draft_set_model,
)
from launchpad.domain.enums import Channel, ContentStatus
from launchpad.llm.service import CallContext, llm
from launchpad.llm.types import Purpose
from launchpad.models import Asset, BrandKit, ContentItem, Workspace
from launchpad.prompts import load_prompt
from launchpad.storage import get_storage

log = structlog.get_logger(__name__)

ProgressFn = Callable[[dict[str, Any]], Awaitable[None]]
MAX_CRITIQUE_ROUNDS = 2
GOOD_ENOUGH = 8
LABELS = "ABCDEFGH"

CHANNEL_GUIDES: dict[Channel, str] = {
    Channel.INSTAGRAM_POST: "A single-image Instagram post. Caption: hook line, short body with line breaks, CTA. Describe the image (no text baked into it).",
    Channel.INSTAGRAM_CAROUSEL: "An Instagram carousel. Slide 1 = hook, middle slides = value (one idea each), last slide = CTA. Caption complements the slides.",
    Channel.LINKEDIN_POST: "A LinkedIn post from the business. Professional but human; short paragraphs; insight or story first; no hashtag spam.",
    Channel.X_POST: "An X (Twitter) post. 'single' = one post; 'thread' = 2-10 numbered posts that each stand alone. Punchy.",
    Channel.EMAIL: "A marketing email: 3 subject-line variants (different approaches), a preheader, then 2-8 sections (hero, text, bullets, quote, cta). Exactly one 'cta' section with a button label; button_url null unless a URL is given.",
}  # fmt: skip


def limits_text(channel: Channel) -> list[str]:
    r = RULES[channel]
    lines: list[str] = []
    if r.max_chars:
        lines.append(f"Max {r.max_chars} characters (including hashtags).")
    if r.fold_chars:
        lines.append(
            f"The feed cuts off after ~{r.fold_chars} characters — the hook must come first."
        )
    if r.hashtags_max:
        lo, hi = r.hashtags_recommended
        lines.append(f"{lo}-{hi} hashtags recommended, never more than {r.hashtags_max}.")
    if not r.links_clickable:
        lines.append("Links aren't clickable in captions; say 'link in bio'.")
    if channel == Channel.INSTAGRAM_CAROUSEL:
        lines.append(
            f"{CAROUSEL_SLIDES[0]}-{CAROUSEL_SLIDES[1]} slides; headline <= {SLIDE_HEADLINE_MAX} chars, body <= {SLIDE_BODY_MAX} chars."
        )
    if channel == Channel.X_POST:
        lines.append(
            f"Each post <= 280 characters (URLs count as 23). Threads: {THREAD_POSTS[0]}-{THREAD_POSTS[1]} posts."
        )
    if channel == Channel.EMAIL:
        lines.append(
            f"Subjects <= {EMAIL_SUBJECT_MAX} characters; preheader {EMAIL_PREHEADER[0]}-{EMAIL_PREHEADER[1]} characters."
        )
    return lines


@dataclass
class Iteration:
    round: int  # 0 = first draft
    content: dict[str, Any]
    violations: list[dict[str, str]]
    scores: dict[str, int] | None = None  # critique of *this* version
    issues: list[str] = field(default_factory=list)


@dataclass
class VariantResult:
    label: str
    angle: str
    hook: str
    rationale: str
    content: dict[str, Any]
    violations: list[dict[str, str]]
    iterations: list[Iteration]
    llm_call_ids: list[str]
    item_id: uuid.UUID | None = None

    @property
    def final_scores(self) -> dict[str, int] | None:
        scored = [it.scores for it in self.iterations if it.scores]
        return scored[-1] if scored else None

    @property
    def blocked(self) -> bool:
        return any(v["severity"] == "error" for v in self.violations)


async def _noop(_: dict[str, Any]) -> None:
    return None


def _clean(channel: Channel, content: dict[str, Any]) -> dict[str, Any]:
    if "hashtags" in content:
        content = {**content, "hashtags": normalize_hashtags(content["hashtags"])}
    return content


def _violations(channel: Channel, content: dict[str, Any]) -> list[dict[str, str]]:
    return [asdict(v) for v in validate(channel, content)]


def main_text(channel: Channel, content: dict[str, Any]) -> str:
    if channel in (Channel.INSTAGRAM_POST, Channel.INSTAGRAM_CAROUSEL):
        return str(content.get("caption", ""))
    if channel == Channel.LINKEDIN_POST:
        return str(content.get("text", ""))
    if channel == Channel.X_POST:
        return "\n\n".join(content.get("posts", []))
    if channel == Channel.EMAIL:
        subjects = content.get("subject_variants") or [""]
        return str(subjects[0])
    return json.dumps(content)


def _prompt_vars(bctx: BrandContext, channel: Channel) -> dict[str, Any]:
    return {
        **bctx.as_prompt_vars(),
        "channel_label": RULES[channel].label,
        "channel_guide": CHANNEL_GUIDES[channel],
        "limits": limits_text(channel),
    }


async def critique_content(
    ctx: CallContext,
    bctx: BrandContext,
    *,
    channel: Channel,
    brief: str,
    angle: str,
    content: dict[str, Any],
    violations: list[dict[str, str]],
) -> tuple[CritiqueScores, list[str], dict[str, Any], uuid.UUID]:
    prompt = load_prompt("critique_content").render(
        **_prompt_vars(bctx, channel),
        brief=brief,
        angle=angle,
        draft_json=json.dumps(content, ensure_ascii=False, indent=1),
        violations=[v["message"] for v in violations if v["severity"] == "error"],
    )
    result, call_id = await llm.generate(
        ctx, Purpose.CRITIQUE, prompt, task="critique_content",
        schema=critique_model(channel), temperature=0.3, max_tokens=8192,
    )  # fmt: skip
    assert result.parsed is not None
    revised = _clean(channel, result.parsed.revised.model_dump())
    return result.parsed.scores, list(result.parsed.issues), revised, call_id


async def _review_loop(
    ctx: CallContext,
    bctx: BrandContext,
    variant: VariantResult,
    *,
    channel: Channel,
    brief: str,
    progress: ProgressFn,
) -> None:
    for rnd in range(1, MAX_CRITIQUE_ROUNDS + 1):
        current = variant.iterations[-1]
        await progress({"type": "step", "key": f"review_{variant.label}_{rnd}", "status": "running",
                        "label": f"Reviewing variant {variant.label} (round {rnd})"})  # fmt: skip
        scores, issues, revised, call_id = await critique_content(
            ctx, bctx, channel=channel, brief=brief, angle=variant.angle,
            content=current.content, violations=current.violations,
        )  # fmt: skip
        variant.llm_call_ids.append(str(call_id))
        current.scores, current.issues = scores.model_dump(), issues
        good = scores.minimum() >= GOOD_ENOUGH and not any(
            v["severity"] == "error" for v in current.violations
        )
        await progress({"type": "step", "key": f"review_{variant.label}_{rnd}", "status": "done",
                        "label": f"Variant {variant.label}: avg {scores.average()}/10"})  # fmt: skip
        if good:
            break
        await progress({"type": "step", "key": f"revise_{variant.label}_{rnd}", "status": "done",
                        "label": f"Revised variant {variant.label}"})  # fmt: skip
        variant.iterations.append(Iteration(rnd, revised, _violations(channel, revised)))
    final = variant.iterations[-1]
    variant.content, variant.violations = final.content, final.violations


async def write_content(
    db: AsyncSession,
    ws: Workspace,
    ctx: CallContext,
    *,
    channel: Channel,
    brief: str,
    n_variants: int = 3,
    critique: bool = True,
    campaign_id: uuid.UUID | None = None,
    campaign_goal: str | None = None,
    keep_angle: str | None = None,
    save: bool = True,
    progress: ProgressFn = _noop,
) -> list[VariantResult]:
    if channel not in CONTENT_MODELS:
        raise ValueError(
            f"{channel} isn't a text channel; posters are created in the poster studio."
        )

    await progress(
        {"type": "step", "key": "brand", "status": "running", "label": "Reading brand kit"}
    )
    await progress(
        {"type": "step", "key": "retrieve", "status": "running", "label": "Retrieving brand docs"}
    )
    bctx = await build_brand_context(db, ws, ctx, query=brief)
    await progress({"type": "step", "key": "brand", "status": "done", "label": "Read brand kit"})
    await progress({"type": "step", "key": "retrieve", "status": "done",
                    "label": f"Found {len(bctx.knowledge)} relevant brand facts" if bctx.knowledge else "No brand docs matched (writing without them)"})  # fmt: skip

    full_brief = (
        brief
        if not keep_angle
        else f"{brief}\n\nKeep this angle but write a fresh take: {keep_angle}"
    )
    prompt = load_prompt("write_content").render(
        **_prompt_vars(bctx, channel), brief=full_brief, n=n_variants, campaign_goal=campaign_goal
    )
    await progress({"type": "step", "key": "write", "status": "running",
                    "label": f"Writing {n_variants} variant{'s' if n_variants != 1 else ''}"})  # fmt: skip
    result, write_call = await llm.generate(
        ctx, Purpose.WRITING, prompt, task="write_content",
        schema=draft_set_model(channel, n_variants), max_tokens=12000,
    )  # fmt: skip
    assert result.parsed is not None
    await progress(
        {"type": "step", "key": "write", "status": "done", "label": f"Wrote {n_variants} drafts"}
    )

    variants: list[VariantResult] = []
    for i, v in enumerate(result.parsed.variants):
        content = _clean(channel, v.content.model_dump())
        violations = _violations(channel, content)
        variants.append(
            VariantResult(
                label=LABELS[i], angle=v.angle, hook=v.hook, rationale=v.rationale,
                content=content, violations=violations,
                iterations=[Iteration(0, content, violations)], llm_call_ids=[str(write_call)],
            )
        )  # fmt: skip
        await progress({"type": "variant", "label": LABELS[i], "angle": v.angle, "stage": "draft",
                        "content": content, "violations": violations})  # fmt: skip

    if critique:
        await asyncio.gather(
            *(
                _review_loop(ctx, bctx, v, channel=channel, brief=brief, progress=progress)
                for v in variants
            )
        )

    if save:
        await progress(
            {"type": "step", "key": "save", "status": "running", "label": "Saving drafts"}
        )
        group = uuid.uuid4()
        prompt_versions = {"write_content": prompt.version}
        if critique:
            prompt_versions["critique_content"] = load_prompt("critique_content").version
        for v in variants:
            item = await _save_item(
                db, ws, bctx, channel=channel, brief=brief, variant=v, group=group,
                campaign_id=campaign_id, prompt_versions=prompt_versions,
            )  # fmt: skip
            v.item_id = item.id
        await db.commit()
        await progress(
            {"type": "step", "key": "save", "status": "done", "label": "Saved as drafts"}
        )
    return variants


async def _logo_url(db: AsyncSession, ws: Workspace) -> str | None:
    from sqlalchemy import select

    kit = await db.scalar(select(BrandKit).where(BrandKit.workspace_id == ws.id))
    if kit is None or kit.logo_asset_id is None:
        return None
    logo = await db.get(Asset, kit.logo_asset_id)
    if logo is None:
        return None
    url = await get_storage().signed_url(logo.storage_key, expires_s=7 * 24 * 3600)
    return (
        url if url.startswith("http") else None
    )  # local relative links don't work in mail clients


async def email_payload(
    db: AsyncSession, ws: Workspace, bctx: BrandContext, content: dict[str, Any]
) -> dict[str, Any]:
    rendered = render_email(
        EmailContent.model_validate(content),
        business_name=ws.name, website=ws.website, locations=list(ws.locations or []),
        primary_color=bctx.primary_color, secondary_color=bctx.secondary_color,
        logo_url=await _logo_url(db, ws),
    )  # fmt: skip
    return {"html": rendered.html, "text": rendered.text}


async def _save_item(
    db: AsyncSession,
    ws: Workspace,
    bctx: BrandContext,
    *,
    channel: Channel,
    brief: str,
    variant: VariantResult,
    group: uuid.UUID,
    campaign_id: uuid.UUID | None,
    prompt_versions: dict[str, str],
) -> ContentItem:
    payload = dict(variant.content)
    if channel == Channel.EMAIL:
        payload["rendered"] = await email_payload(db, ws, bctx, variant.content)
    scores = variant.final_scores
    item = ContentItem(
        workspace_id=ws.id,
        campaign_id=campaign_id,
        channel=channel,
        title=variant.angle[:200],
        body=main_text(channel, variant.content),
        payload=payload,
        hashtags=list(variant.content.get("hashtags", [])),
        variant_group=group,
        variant_label=variant.label,
        status=ContentStatus.DRAFT,
        critique_score=round(CritiqueScores(**scores).average()) if scores else None,
        generation={
            "brief": brief,
            "angle": variant.angle,
            "hook": variant.hook,
            "rationale": variant.rationale,
            "iterations": [asdict(it) for it in variant.iterations],
            "violations": variant.violations,
            "llm_call_ids": variant.llm_call_ids,
            "prompt_versions": prompt_versions,
            "knowledge_sources": sorted({k.source for k in bctx.knowledge}),
        },
    )
    db.add(item)
    await db.flush()
    return item


async def suggest_hashtags(
    db: AsyncSession, ws: Workspace, ctx: CallContext, *, channel: Channel, content_text: str
) -> dict[str, list[str]]:
    from launchpad.content.industries import profile_for

    r = RULES[channel]
    max_tags = r.hashtags_max or 10
    prompt = load_prompt("suggest_hashtags").render(
        business_name=ws.name, industry=ws.industry.value, locations=list(ws.locations or []),
        seed_hashtags=list(profile_for(ws.industry).seed_hashtags), channel_label=r.label,
        max_tags=max_tags, content_text=content_text[:3000],
    )  # fmt: skip
    result, _ = await llm.generate(
        ctx,
        Purpose.CRITIQUE,
        prompt,
        task="suggest_hashtags",
        schema=HashtagBuckets,
        temperature=0.4,
    )
    assert result.parsed is not None
    buckets: dict[str, list[str]] = {}
    seen: set[str] = set()
    # Priority when trimming to the platform maximum: branded > niche > local > broad.
    budget = max_tags
    for name in ("branded", "niche", "local", "broad"):
        tags = [
            t for t in normalize_hashtags(getattr(result.parsed, name)) if t.lower() not in seen
        ]
        tags = tags[: max(budget, 0)]
        budget -= len(tags)
        seen |= {t.lower() for t in tags}
        buckets[name] = tags
    return {k: buckets[k] for k in ("broad", "niche", "branded", "local")}


def revalidate(channel: Channel, content: dict[str, Any]) -> list[dict[str, str]]:
    return _violations(channel, _clean(channel, content))


def parse_content(channel: Channel, content: dict[str, Any]) -> BaseModel:
    return CONTENT_MODELS[channel].model_validate(content)
