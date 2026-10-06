"""Live end-to-end agent run against the configured provider (LLM_PROVIDER / LLM_MODEL in .env).
Skipped unless RUN_LIVE_TESTS=1: it costs money and needs quota.

    RUN_LIVE_TESTS=1 pytest -m live tests/agent/test_live_agent.py -v
"""

from __future__ import annotations

import os
import re
import uuid

import pytest
from sqlalchemy import select

from launchpad.agent.runner import execute_run
from launchpad.config import get_settings
from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import AgentRunStatus, Industry
from launchpad.models import AgentEvent, AgentRun, BrandKit, ContentItem, User, Workspace

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1"),
]

CAFE = "Plan a 1-week campaign for a café launching cold coffee, Instagram + email"


async def test_cafe_cold_coffee_campaign_reaches_approval() -> None:
    s = get_settings()
    if not s.llm_provider or not s.llm_model:
        pytest.skip("LLM_PROVIDER / LLM_MODEL not configured")
    async with get_sessionmaker()() as db:
        user = User(email=f"{uuid.uuid4().hex}@example.com")
        db.add(user)
        await db.flush()
        ws = Workspace(
            owner_id=user.id, name="Brew Lab", industry=Industry.FOOD, locations=["Pune"],
            description="Specialty coffee bar in Koregaon Park; cold coffee launches Monday.",
            audience="College students and young professionals",
        )  # fmt: skip
        ws.brand_kit = BrandKit(voice_tone="Friendly, upbeat, a little playful. Short sentences.")
        db.add(ws)
        await db.flush()
        run = AgentRun(
            workspace_id=ws.id, user_id=user.id, thread_id=f"t_live_{uuid.uuid4().hex[:8]}",
            input=CAFE, title=CAFE, status=AgentRunStatus.RUNNING, token_budget=200_000,
        )  # fmt: skip
        db.add(run)
        await db.commit()

    status = await execute_run(run.id)
    async with get_sessionmaker()() as db:
        events = list(
            await db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.id).order_by(AgentEvent.seq)
            )
        )
        drafts = list(
            await db.scalars(select(ContentItem).where(ContentItem.agent_run_id == run.id))
        )
    errors = [e.data for e in events if e.type == "error"]
    assert status == AgentRunStatus.AWAITING_APPROVAL, errors
    tools = [e.data["tool"] for e in events if e.type == "tool_call"]
    assert "plan_campaign" in tools
    plan_results = [
        e.data for e in events if e.type == "tool_result" and e.data["tool"] == "plan_campaign"
    ]
    assert any(r["ok"] for r in plan_results)  # a validated calendar was produced
    channels = {d.channel.value for d in drafts}
    assert "instagram_post" in channels or "instagram_carousel" in channels
    assert "email" in channels
    assert all(d.status.value == "draft" for d in drafts)  # nothing approved without the user
    final = next(e.data.get("final") or "" for e in events if e.type == "approval_required")
    assert not re.search(
        r"\b(i|we)(?:'ve| have)?\s+(published|posted|scheduled|sent)\b", final, re.I
    )
