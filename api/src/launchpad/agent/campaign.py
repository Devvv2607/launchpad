"""plan_campaign: goal + dates + channels -> a validated content calendar."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field, create_model, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.agent.calendar import as_dict, between
from launchpad.content.context import build_brand_context
from launchpad.domain.enums import CampaignGoal, Channel
from launchpad.llm.service import CallContext, llm
from launchpad.llm.types import Purpose
from launchpad.models import Workspace
from launchpad.prompts import load_prompt


class CalendarItem(BaseModel):
    model_config = {"extra": "forbid"}
    date: date
    channel: Channel
    angle: str = Field(description="What this post is about, in a few words")
    cta: str = Field(description="The call to action")
    rationale: str = Field(description="Why this, on this day")
    observance: str | None = Field(
        default=None, description="Festival/occasion this ties into, if any"
    )


class _PlanBase(BaseModel):
    model_config = {"extra": "forbid"}
    summary: str = Field(description="Two sentences: the campaign idea and how it builds")
    items: list[Any]


def campaign_plan_model(
    start: date, end: date, channels: list[Channel], max_per_day: int, observances: dict[str, date]
) -> type[_PlanBase]:
    allowed = set(channels)
    days = (end - start).days + 1

    def check(self: _PlanBase) -> _PlanBase:
        items: list[CalendarItem] = self.items
        problems = []
        outside = sorted({i.date.isoformat() for i in items if not start <= i.date <= end})
        if outside:
            problems.append(f"Dates outside {start}..{end}: {', '.join(outside)}.")
        wrong = sorted({i.channel.value for i in items if i.channel not in allowed})
        if wrong:
            problems.append(f"Only use channels {sorted(c.value for c in allowed)}; got {wrong}.")
        busy = [d.isoformat() for d, n in Counter(i.date for i in items).items() if n > max_per_day]
        if busy:
            problems.append(
                f"At most {max_per_day} item(s) per day; too many on {', '.join(sorted(busy))}."
            )
        if (
            days >= 7
            and items
            and len({i.date for i in items}) < min(len(items), max(2, days // 4))
        ):
            problems.append("Spread the items across the date range instead of bunching them.")
        for i in items:
            obs = observances.get((i.observance or "").strip().lower())
            if i.observance and obs is not None and not obs - timedelta(days=7) <= i.date <= obs:
                problems.append(
                    f"'{i.angle}' ties into {i.observance} ({obs}) but is dated {i.date}; "
                    "post on or shortly before it."
                )
        if problems:
            raise ValueError(" ".join(problems))
        return self

    model: type[_PlanBase] = create_model(
        "CampaignPlan",
        __base__=_PlanBase,
        # pydantic types __validators__ as plain callables; decorated validators are what it expects
        __validators__={"_check": model_validator(mode="after")(check)},  # type: ignore[dict-item]
        items=(list[CalendarItem], Field(min_length=1, max_length=max(1, days * max_per_day))),
    )
    return model


async def plan_campaign(
    db: AsyncSession,
    ws: Workspace,
    ctx: CallContext,
    *,
    goal: CampaignGoal,
    brief: str,
    start: date,
    end: date,
    channels: list[Channel],
    max_per_day: int = 1,
) -> dict[str, Any]:
    if end < start:
        raise ValueError("The end date is before the start date.")
    if (end - start).days > 92:
        raise ValueError("Plan at most three months at a time.")
    obs = between(start - timedelta(days=0), end)
    bctx = await build_brand_context(db, ws, ctx, query=brief)
    prompt = load_prompt("plan_campaign").render(
        **bctx.as_prompt_vars(),
        goal=goal.value,
        brief=brief,
        start=start.isoformat(),
        end=end.isoformat(),
        start_weekday=start.strftime("%A"),
        channels=[c.value for c in channels],
        max_per_day=max_per_day,
        observances=[as_dict(o) for o in obs],
    )
    schema = campaign_plan_model(
        start, end, channels, max_per_day, {o.name.lower(): o.day for o in obs}
    )
    result, call_id = await llm.generate(
        ctx,
        Purpose.PLANNING,
        prompt,
        task="plan_campaign",
        schema=schema,
        temperature=0.5,
        max_tokens=8000,
    )
    assert result.parsed is not None
    plan = result.parsed.model_dump(mode="json")
    plan["items"] = sorted(plan["items"], key=lambda i: (i["date"], i["channel"]))
    plan["observances_considered"] = [as_dict(o) for o in obs]
    plan["llm_call_id"] = str(call_id)
    return plan
