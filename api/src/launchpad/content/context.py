"""Assembles everything the writer needs to know about a business, from real data only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.content.industries import IndustryProfile, profile_for
from launchpad.llm.service import CallContext
from launchpad.models import BrandKit, Workspace
from launchpad.rag.service import Retrieved, retrieve_brand_context


@dataclass
class BrandContext:
    business_name: str
    industry: str
    industry_profile: IndustryProfile
    description: str | None
    audience: str | None
    locations: list[str]
    website: str | None
    voice_tone: str | None
    voice_profile: dict[str, Any] | None
    do_words: list[str]
    dont_words: list[str]
    sample_posts: list[str]
    primary_color: str | None
    secondary_color: str | None
    knowledge: list[Retrieved] = field(default_factory=list)

    def as_prompt_vars(self) -> dict[str, Any]:
        return {
            "business_name": self.business_name,
            "industry": self.industry,
            "industry_focus": self.industry_profile.focus,
            "industry_ideas": self.industry_profile.content_ideas,
            "industry_avoid": self.industry_profile.avoid,
            "description": self.description,
            "audience": self.audience,
            "locations": self.locations,
            "website": self.website,
            "voice_tone": self.voice_tone,
            "voice_profile": self.voice_profile,
            "do_words": self.do_words,
            "dont_words": self.dont_words,
            "sample_posts": self.sample_posts[:3],
            "knowledge": [
                {"n": i + 1, "text": k.content, "source": k.source, "heading": k.heading}
                for i, k in enumerate(self.knowledge)
            ],
        }


async def build_brand_context(
    db: AsyncSession, ws: Workspace, ctx: CallContext, *, query: str | None, k: int = 4
) -> BrandContext:
    kit = await db.scalar(select(BrandKit).where(BrandKit.workspace_id == ws.id))
    knowledge: list[Retrieved] = []
    if query:
        knowledge, _ = await retrieve_brand_context(db, ctx, query, k=k)
    return BrandContext(
        business_name=ws.name,
        industry=ws.industry.value,
        industry_profile=profile_for(ws.industry),
        description=ws.description,
        audience=ws.audience,
        locations=list(ws.locations or []),
        website=ws.website,
        voice_tone=kit.voice_tone if kit else None,
        voice_profile=kit.voice_profile if kit else None,
        do_words=list(kit.do_words or []) if kit else [],
        dont_words=list(kit.dont_words or []) if kit else [],
        sample_posts=list(kit.sample_posts or []) if kit else [],
        primary_color=kit.primary_color if kit else None,
        secondary_color=kit.secondary_color if kit else None,
        knowledge=knowledge,
    )
