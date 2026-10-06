"""Agent tools: typed Pydantic inputs, plain-dict outputs, one registry.

Safety rule enforced in code: no tool may publish, send or schedule anything outbound. Tools
can only read, research, plan and create *drafts*; approval is a human decision applied by the
approval node from the user's explicit choices. `assert_no_outbound()` runs at import time and
in tests, so adding an outbound tool fails loudly.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.agent.calendar import as_dict, between
from launchpad.agent.campaign import plan_campaign
from launchpad.agent.research import ResearchNotConfigured, get_search
from launchpad.content.context import build_brand_context
from launchpad.content.engine import critique_content, main_text, suggest_hashtags, write_content
from launchpad.content.platform_rules import validate
from launchpad.domain.enums import CampaignGoal, CampaignStatus, Channel, ContentStatus
from launchpad.llm.service import CallContext
from launchpad.models import Campaign, ContentItem, Workspace

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class ToolContext:
    db: AsyncSession
    ws: Workspace
    ctx: CallContext
    run_id: uuid.UUID
    emit: Emit
    created_item_ids: list[str] = field(default_factory=list)


Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Handler
    progress_label: str  # shown in the UI timeline while it runs
    outbound: bool = False  # True would mean "reaches the outside world" — forbidden


class _In(BaseModel):
    model_config = {"extra": "forbid"}


# ------------------------------------------------------------------------------- inputs


class BrandContextIn(_In):
    query: str = Field(description="What you need to know, e.g. 'menu prices' or 'brand voice'")


class ResearchIn(_In):
    query: str = Field(
        description="Search query about trends, competitors or an occasion, in India"
    )
    days_ahead: int = Field(
        default=60, ge=1, le=365, description="Festival window to include, in days from today"
    )


class PlanCampaignIn(_In):
    goal: CampaignGoal
    brief: str
    start_date: date
    end_date: date
    channels: list[Channel] = Field(min_length=1)
    max_per_day: int = Field(default=1, ge=1, le=3)
    campaign_id: uuid.UUID | None = Field(
        default=None, description="Save the plan to this campaign"
    )


class WriteContentIn(_In):
    channel: Literal["instagram_post", "instagram_carousel", "linkedin_post", "x_post", "email"]
    brief: str = Field(description="Everything the writer needs: topic, offer, dates, audience")
    n_variants: int = Field(default=2, ge=1, le=4)


class CritiqueIn(_In):
    item_id: uuid.UUID
    apply_revision: bool = Field(default=False, description="Save the revised version to the draft")


class HashtagsIn(_In):
    channel: Literal["instagram_post", "instagram_carousel", "linkedin_post", "x_post"]
    text: str


class EmailIn(_In):
    brief: str


class NoArgs(_In):
    pass


class ImageIn(_In):
    description: str


class PosterIn(_In):
    headline: str
    subtext: str | None = None


class ScheduleIn(_In):
    item_id: uuid.UUID
    when: str


# ------------------------------------------------------------------------------- handlers


async def _brand(tc: ToolContext, a: BrandContextIn) -> dict[str, Any]:
    b = await build_brand_context(tc.db, tc.ws, tc.ctx, query=a.query, k=5)
    return {
        "business": b.business_name,
        "industry": b.industry,
        "audience": b.audience,
        "locations": b.locations,
        "voice": b.voice_profile.get("summary") if b.voice_profile else b.voice_tone,
        "do_words": b.do_words,
        "dont_words": b.dont_words,
        "facts": [
            {
                "n": i + 1,
                "text": k.content,
                "source": k.source,
                "heading": k.heading,
                "score": k.score,
            }
            for i, k in enumerate(b.knowledge)
        ],
        "note": None if b.knowledge else "No brand documents matched; don't invent specifics.",
    }


async def _research(tc: ToolContext, a: ResearchIn) -> dict[str, Any]:
    today = _today(tc.ws)
    festivals = [as_dict(o) for o in between(today, today + timedelta(days=a.days_ahead))]
    out: dict[str, Any] = {"festivals": festivals, "today": today.isoformat()}
    try:
        sources = await get_search().search(a.query, max_results=5)
        out["sources"] = [
            {
                "n": i + 1,
                "title": s.title,
                "url": s.url,
                "snippet": s.snippet,
                "published": s.published,
            }
            for i, s in enumerate(sources)
        ]
        await tc.emit(
            "research",
            {"query": a.query, "sources": [{"title": s.title, "url": s.url} for s in sources]},
        )
    except ResearchNotConfigured as exc:
        out["sources"] = []
        out["web_research"] = str(exc)
    return out


async def _plan(tc: ToolContext, a: PlanCampaignIn) -> dict[str, Any]:
    plan = await plan_campaign(
        tc.db, tc.ws, tc.ctx, goal=a.goal, brief=a.brief, start=a.start_date, end=a.end_date,
        channels=list(a.channels), max_per_day=a.max_per_day,
    )  # fmt: skip
    if a.campaign_id:
        campaign = await tc.db.get(Campaign, a.campaign_id)
        if campaign is None or campaign.workspace_id != tc.ws.id:
            return {"error": "Campaign not found in this workspace.", "plan": plan}
        campaign.plan = plan
        campaign.status = CampaignStatus.PLANNED
        await tc.db.commit()
        plan["saved_to_campaign"] = str(campaign.id)
    return plan


async def _write(tc: ToolContext, a: WriteContentIn) -> dict[str, Any]:
    channel = Channel(a.channel)
    variants = await write_content(
        tc.db, tc.ws, tc.ctx, channel=channel, brief=a.brief, n_variants=a.n_variants,
        agent_run_id=tc.run_id,
    )  # fmt: skip
    items = []
    for v in variants:
        if v.item_id is None:
            continue
        tc.created_item_ids.append(str(v.item_id))
        scores = v.final_scores
        summary = {
            "item_id": str(v.item_id),
            "label": v.label,
            "channel": channel.value,
            "angle": v.angle,
            "preview": main_text(channel, v.content)[:280],
            "avg_score": round(sum(scores.values()) / len(scores), 1) if scores else None,
            "blocked_by_platform_rules": v.blocked,
        }
        items.append(summary)
        await tc.emit("item_created", summary)
    return {"items": items, "status": "saved as drafts awaiting the user's approval"}


async def _critique(tc: ToolContext, a: CritiqueIn) -> dict[str, Any]:
    item = await tc.db.get(ContentItem, a.item_id)
    if item is None or item.workspace_id != tc.ws.id:
        return {"error": "Content item not found in this workspace."}
    if item.status not in (ContentStatus.DRAFT, ContentStatus.IN_REVIEW):
        return {"error": f"Item is {item.status.value}; only drafts can be revised."}
    content = {k: v for k, v in (item.payload or {}).items() if k != "rendered"}
    bctx = await build_brand_context(
        tc.db, tc.ws, tc.ctx, query=(item.generation or {}).get("brief")
    )
    violations = [v.__dict__ for v in validate(item.channel, content)]
    scores, issues, revised, call_id = await critique_content(
        tc.ctx, bctx, channel=item.channel, brief=(item.generation or {}).get("brief", ""),
        angle=item.title or "", content=content, violations=violations,
    )  # fmt: skip
    applied = False
    revised_violations = [v.__dict__ for v in validate(item.channel, revised)]
    if a.apply_revision and not any(v["severity"] == "error" for v in revised_violations):
        item.payload = {
            **revised,
            **({"rendered": item.payload["rendered"]} if "rendered" in item.payload else {}),
        }
        item.body = main_text(item.channel, revised)
        item.hashtags = list(revised.get("hashtags", []))
        gen = dict(item.generation or {})
        gen["violations"] = revised_violations
        gen.setdefault("agent_revisions", []).append(
            {"scores": scores.model_dump(), "issues": issues, "llm_call_id": str(call_id)}
        )
        item.generation = gen
        await tc.db.commit()
        applied = True
    return {
        "item_id": str(item.id),
        "scores": scores.model_dump(),
        "issues": issues,
        "revision_applied": applied,
    }


async def _hashtags(tc: ToolContext, a: HashtagsIn) -> dict[str, Any]:
    return await suggest_hashtags(
        tc.db, tc.ws, tc.ctx, channel=Channel(a.channel), content_text=a.text
    )


async def _email(tc: ToolContext, a: EmailIn) -> dict[str, Any]:
    return await _write(tc, WriteContentIn(channel="email", brief=a.brief, n_variants=1))


async def _analytics(tc: ToolContext, a: NoArgs) -> dict[str, Any]:
    return {
        "status": "no_data",
        "message": "There is no performance data yet: no channels are connected and nothing has been "
        "published. Analytics from real platform insights arrive in Phase 6. Do not estimate metrics.",
    }


def _unavailable(what: str, phase: int) -> Handler:
    async def handler(tc: ToolContext, a: Any) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "message": f"{what} isn't available yet (coming in Phase {phase}). Tell the user plainly; "
            "don't describe an image, poster or schedule as if it exists.",
        }

    return handler


def _today(ws: Workspace) -> date:
    from datetime import datetime

    return datetime.now(ZoneInfo(ws.timezone)).date()


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("get_brand_context", "Brand kit, voice and facts retrieved from the brand's own documents (with sources). Call before writing.", BrandContextIn, _brand, "Reading brand kit"),
        Tool("research_trends", "Web research on trends/competitors in India (returns source URLs to cite) plus upcoming Indian festivals and observances.", ResearchIn, _research, "Researching trends"),
        Tool("plan_campaign", "Turn a goal, date range and channels into a dated content calendar (validated). Optionally saves to a campaign.", PlanCampaignIn, _plan, "Planning the calendar"),
        Tool("write_content", "Write N distinct variants for one channel, reviewed against brand voice and platform rules, saved as DRAFTS for the user to approve.", WriteContentIn, _write, "Writing variants"),
        Tool("critique_content", "Score an existing draft and optionally save an improved revision.", CritiqueIn, _critique, "Reviewing a draft"),
        Tool("suggest_hashtags", "Suggest broad/niche/branded/local hashtags for a piece of text.", HashtagsIn, _hashtags, "Choosing hashtags"),
        Tool("build_email", "Write a marketing email (3 subject lines, preheader, sections, rendered HTML) saved as a draft.", EmailIn, _email, "Building the email"),
        Tool("get_analytics", "Real performance data from connected channels.", NoArgs, _analytics, "Checking analytics"),
        Tool("generate_image", "Generate a background/hero image (no text in the image).", ImageIn, _unavailable("Image generation", 4), "Generating image"),
        Tool("create_poster", "Render a poster in standard sizes.", PosterIn, _unavailable("Poster rendering", 4), "Rendering poster"),
        Tool("schedule_content", "Schedule an APPROVED item for publishing.", ScheduleIn, _unavailable("Scheduling", 5), "Scheduling"),
    ]
}  # fmt: skip


def assert_no_outbound() -> None:
    outbound = [t.name for t in TOOLS.values() if t.outbound]
    if outbound:
        raise RuntimeError(f"Agent tools must never publish or send: {outbound}")


assert_no_outbound()


async def current_item_statuses(db: AsyncSession, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = await db.scalars(
        select(ContentItem).where(ContentItem.id.in_([uuid.UUID(i) for i in ids]))
    )
    return {str(r.id): r.status.value for r in rows}
