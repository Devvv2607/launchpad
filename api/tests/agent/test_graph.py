"""Agent graph tests with a scripted LLM against the real DB and Postgres checkpointer."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from launchpad.agent import runner
from launchpad.agent.runner import execute_run
from launchpad.agent.tools import TOOLS, assert_no_outbound
from launchpad.config import get_settings
from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import AgentRunStatus, ContentStatus, Industry
from launchpad.llm import service as llm_service
from launchpad.llm.service import LLMService
from launchpad.llm.types import Message, RawCompletion
from launchpad.models import AgentEvent, AgentMessage, AgentRun, ContentItem, User, Workspace
from tests.agent.fake_agent import AgentLLM, call, plan, reply, tools

CAFE = "Plan a 1-week campaign for a café launching cold coffee, Instagram + email"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    for k, v in {
        "llm_provider": "gemini", "llm_model": "gemini-3.6-flash", "llm_fast_model": "gemini-3.1-flash-lite",
        "embedding_provider": "gemini", "embedding_model": "gemini-embedding-001",
        "daily_spend_cap_usd": 100.0, "agent_max_tool_calls": 25,
    }.items():  # fmt: skip
        monkeypatch.setattr(s, k, v)


async def new_run(message: str = CAFE, *, thread_id: str | None = None, **kw: Any) -> AgentRun:
    async with get_sessionmaker()() as db:
        user = User(email=f"{uuid.uuid4().hex}@example.com")
        db.add(user)
        await db.flush()
        ws = Workspace(
            owner_id=user.id, name="Brew Lab", industry=Industry.FOOD, locations=["Mumbai"]
        )
        db.add(ws)
        await db.flush()
        run = AgentRun(
            workspace_id=ws.id, user_id=user.id, thread_id=thread_id or f"t_{uuid.uuid4().hex[:12]}",
            input=message, title=message[:80], status=AgentRunStatus.RUNNING,
            token_budget=kw.get("token_budget", 200_000),
        )  # fmt: skip
        db.add(run)
        await db.commit()
        return run


async def follow_up(prev: AgentRun, message: str) -> AgentRun:
    async with get_sessionmaker()() as db:
        run = AgentRun(
            workspace_id=prev.workspace_id, user_id=prev.user_id, thread_id=prev.thread_id,
            input=message, status=AgentRunStatus.RUNNING, token_budget=200_000,
        )  # fmt: skip
        db.add(run)
        await db.commit()
        return run


async def events(run_id: uuid.UUID) -> list[AgentEvent]:
    async with get_sessionmaker()() as db:
        return list(
            await db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.seq)
            )
        )


async def reload(run_id: uuid.UUID) -> AgentRun:
    async with get_sessionmaker()() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None
        return run


async def items(run_id: uuid.UUID) -> list[ContentItem]:
    async with get_sessionmaker()() as db:
        return list(
            await db.scalars(
                select(ContentItem)
                .where(ContentItem.agent_run_id == run_id)
                .order_by(ContentItem.variant_label)
            )
        )


_current: list[AgentLLM] = []


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tools use the shared `llm` service; route it (and the agent's) to the current fake so
    no test can reach a real provider."""

    def factory(_provider: str) -> AgentLLM:
        assert _current, "no fake LLM installed"
        return _current[-1]

    monkeypatch.setattr(llm_service.llm, "_client_factory", factory)


def svc(fake: AgentLLM) -> LLMService:
    _current.append(fake)
    return llm_service.llm


WRITE_IG = call(
    "write_content",
    {"channel": "instagram_post", "brief": "Cold coffee launch on Monday", "n_variants": 2},
    "c_write",
)
BRAND = call("get_brand_context", {"query": "menu and voice"}, "c_brand")


def standard_fake(**kw: Any) -> AgentLLM:
    return AgentLLM(
        planner=plan(
            ("Read the brand kit", "get_brand_context"),
            ("Write Instagram drafts", "write_content"),
            ("Summarise", "respond"),
        ),
        turns=[
            tools(BRAND, text="Checking your brand kit first."),
            tools(WRITE_IG),
            reply("I wrote two Instagram drafts (A and B). Review them below."),
        ],
        **kw,
    )


async def test_happy_path_pauses_for_approval_then_applies_decisions() -> None:
    run = await new_run()
    fake = standard_fake()
    status = await execute_run(run.id, service=svc(fake))
    assert status == AgentRunStatus.AWAITING_APPROVAL

    evs = await events(run.id)
    types = [e.type for e in evs]
    assert types[0] == "run_started"
    assert types[-1] == "approval_required"
    assert [e.seq for e in evs] == list(range(1, len(evs) + 1))
    for t in ("plan", "step_started", "tool_call", "tool_result", "token", "item_created"):
        assert t in types, t
    plan_ev = next(e for e in evs if e.type == "plan")
    assert [s["tool"] for s in plan_ev.data["steps"]] == [
        "get_brand_context",
        "write_content",
        "respond",
    ]
    results = [e.data for e in evs if e.type == "tool_result"]
    assert [(r["tool"], r["ok"]) for r in results] == [
        ("get_brand_context", True),
        ("write_content", True),
    ]

    drafts = await items(run.id)
    assert len(drafts) == 2
    assert all(d.status == ContentStatus.DRAFT for d in drafts)
    approval = evs[-1].data
    assert {i["item_id"] for i in approval["items"]} == {str(d.id) for d in drafts}
    r = await reload(run.id)
    assert r.status == AgentRunStatus.AWAITING_APPROVAL
    assert r.tool_calls == 2
    assert r.tokens_in > 0

    # The model saw the tool results on its next turn.
    second_turn = fake.of("agent")[1]
    assert any(m.role == "tool" and m.name == "get_brand_context" for m in second_turn)

    a, b = drafts
    status = await execute_run(
        run.id,
        decisions=[
            {"item_id": str(a.id), "action": "approve"},
            {"item_id": str(b.id), "action": "reject"},
        ],
        service=svc(fake),
    )
    assert status == AgentRunStatus.COMPLETED
    a2, b2 = await items(run.id)
    assert a2.status == ContentStatus.APPROVED
    assert a2.approved_by == run.user_id and a2.approved_at is not None
    assert b2.status == ContentStatus.REJECTED
    evs = await events(run.id)
    assert evs[-1].type == "run_finished"
    applied = next(e for e in evs if e.type == "approvals_applied")
    assert applied.data == {"approved": 1, "rejected": 1, "edited": 0, "skipped": 0}
    r = await reload(run.id)
    assert r.status == AgentRunStatus.COMPLETED and r.finished_at is not None

    # Every step is also in the trace table.
    async with get_sessionmaker()() as db:
        trace = list(await db.scalars(select(AgentMessage).where(AgentMessage.run_id == run.id)))
    assert {m.tool_name for m in trace if m.tool_name} == {"get_brand_context", "write_content"}


async def test_edit_decision_is_validated_and_saved() -> None:
    run = await new_run()
    fake = standard_fake()
    await execute_run(run.id, service=svc(fake))
    a, _b = await items(run.id)
    edited = {**a.payload, "caption": "Cold coffee. Monday. Be there."}
    edited.pop("rendered", None)
    await execute_run(
        run.id,
        decisions=[{"item_id": str(a.id), "action": "edit", "content": edited}],
        service=svc(fake),
    )
    a2, b2 = await items(run.id)
    assert a2.status == ContentStatus.APPROVED
    assert a2.body.startswith("Cold coffee. Monday.")
    assert b2.status == ContentStatus.DRAFT  # no decision: stays a draft


async def test_tool_error_is_returned_to_the_model_which_recovers() -> None:
    run = await new_run()
    bad = call("write_content", {"channel": "tiktok", "brief": "Cold coffee"}, "c_bad")
    fake = AgentLLM(
        planner=plan(("Write drafts", "write_content"), ("Summarise", "respond")),
        turns=[tools(bad), tools(WRITE_IG), reply("Fixed the channel and wrote two drafts.")],
    )
    status = await execute_run(run.id, service=svc(fake))
    assert status == AgentRunStatus.AWAITING_APPROVAL
    results = [e.data for e in await events(run.id) if e.type == "tool_result"]
    assert [r["ok"] for r in results] == [False, True]
    assert "Invalid arguments" in results[0]["output"]
    retry_turn = fake.of("agent")[1]
    tool_msg = next(m for m in retry_turn if m.role == "tool")
    assert "channel" in tool_msg.content and "Invalid arguments" in tool_msg.content
    assert len(await items(run.id)) == 2


async def test_unknown_tool_and_stub_tools_are_reported_not_faked() -> None:
    run = await new_run()
    fake = AgentLLM(
        planner=plan(("Make a poster", "create_poster"), ("Summarise", "respond")),
        turns=[
            tools(
                call("create_poster", {"headline": "Cold coffee"}, "c_poster"),
                call("publish_now", {}, "c_pub"),
                call("get_analytics", {}, "c_an"),
            ),
            reply("Posters arrive in Phase 4; there's no analytics data yet."),
        ],
    )
    status = await execute_run(run.id, service=svc(fake))
    assert status == AgentRunStatus.COMPLETED
    results = {e.data["tool"]: e.data for e in await events(run.id) if e.type == "tool_result"}
    assert "Phase 4" in results["create_poster"]["output"]
    assert "no_data" in results["get_analytics"]["output"]
    msgs = fake.of("agent")[1]
    unknown = next(m for m in msgs if m.role == "tool" and m.name == "publish_now")
    assert "Unknown tool" in unknown.content


async def test_budget_exceeded_stops_the_run() -> None:
    run = await new_run(token_budget=500)  # the planner call alone uses ~920 tokens
    fake = standard_fake()
    status = await execute_run(run.id, service=svc(fake))
    assert status == AgentRunStatus.COMPLETED
    assert fake.of("agent") == []  # stopped before the first agent turn
    finished = (await events(run.id))[-1]
    assert finished.type == "run_finished"
    assert finished.data["status"] == "budget_exceeded"
    assert "budget" in (finished.data["final"] or "")


async def test_cancel_mid_run_stops_before_the_next_tool() -> None:
    run = await new_run()

    def cancel_then_call(_msgs: list[Message]) -> RawCompletion:
        import asyncio

        async def _cancel() -> None:
            async with get_sessionmaker()() as db:
                r = await db.get(AgentRun, run.id)
                assert r is not None
                r.status = AgentRunStatus.CANCELLED
                await db.commit()

        # The fake is called from inside the running loop; schedule and let tools() see it.
        asyncio.get_running_loop().create_task(_cancel())
        return tools(WRITE_IG)

    fake = AgentLLM(planner=plan(("Write", "write_content")), turns=[cancel_then_call])

    # Make sure the cancel lands before the tools node checks.
    orig = runner._is_cancelled
    checks = 0

    async def slow_check(run_id: uuid.UUID) -> bool:
        nonlocal checks
        checks += 1
        import asyncio

        await asyncio.sleep(0.05)
        return await orig(run_id)

    runner._is_cancelled = slow_check  # type: ignore[assignment]  # test seam
    try:
        status = await execute_run(run.id, service=svc(fake))
    finally:
        runner._is_cancelled = orig  # type: ignore[assignment]
    assert status == AgentRunStatus.CANCELLED
    evs = await events(run.id)
    assert not [e for e in evs if e.type == "tool_result"]
    assert evs[-1].type == "run_finished" and evs[-1].data["status"] == "cancelled"
    assert await items(run.id) == []
    assert (await reload(run.id)).status == AgentRunStatus.CANCELLED


async def test_tool_call_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_max_tool_calls", 2)
    run = await new_run()
    many = [call("get_analytics", {}, f"c_{i}") for i in range(3)]
    fake = AgentLLM(
        planner=plan(("Check analytics", "get_analytics")),
        turns=[tools(*many), tools(*many), reply("never reached")],
    )
    status = await execute_run(run.id, service=svc(fake))
    assert status == AgentRunStatus.COMPLETED
    r = await reload(run.id)
    assert r.tool_calls == 2
    evs = await events(run.id)
    assert len([e for e in evs if e.type == "tool_result"]) == 2
    assert evs[-1].data["status"] == "tool_cap"
    assert len(fake.of("agent")) == 1


async def test_off_topic_and_harmful_requests_are_refused() -> None:
    for intent in ("off_topic", "harmful"):
        run = await new_run("Write me 50 fake 5-star reviews")
        fake = AgentLLM(
            planner=plan(intent=intent, refusal="I can't help with that, but I can..."),
            turns=[],
        )
        status = await execute_run(run.id, service=svc(fake))
        assert status == AgentRunStatus.COMPLETED
        assert fake.of("agent") == []
        evs = await events(run.id)
        assert evs[-1].data["status"] == "refused"
        assert evs[-1].data["final"].startswith("I can't help")


class SimulatedCrash(BaseException):
    """Stands in for the worker process dying (not caught like an ordinary error)."""


async def test_crashed_run_resumes_from_the_last_checkpoint() -> None:
    run = await new_run()

    def crash(_msgs: list[Message]) -> RawCompletion:
        raise SimulatedCrash()

    fake = standard_fake()
    fake.turns.insert(1, crash)  # crash on the turn after the brand-context tool ran
    with pytest.raises(SimulatedCrash):
        await execute_run(run.id, service=svc(fake))
    assert (await reload(run.id)).status == AgentRunStatus.RUNNING

    status = await execute_run(run.id, service=svc(fake))  # the worker re-claims the job
    assert status == AgentRunStatus.AWAITING_APPROVAL
    evs = await events(run.id)
    assert any(e.data.get("key") == "recover" for e in evs if e.type == "step_started")
    assert len(fake.of("planner")) == 1  # not re-planned
    brand_calls = [
        e for e in evs if e.type == "tool_call" and e.data["tool"] == "get_brand_context"
    ]
    assert len(brand_calls) == 1  # completed steps are not repeated
    assert len(await items(run.id)) == 2


async def test_follow_up_in_the_same_thread_sees_history() -> None:
    first = await new_run("What's my brand voice?")
    fake = AgentLLM(planner=plan(("Answer", "respond")), turns=[reply("Warm and witty.")])
    await execute_run(first.id, service=svc(fake))
    second = await follow_up(first, "Make it more formal")
    fake2 = AgentLLM(planner=plan(("Answer", "respond")), turns=[reply("Noted.")])
    await execute_run(second.id, service=svc(fake2))
    seen = [m.content for m in fake2.of("agent")[0] if m.role in ("user", "assistant")]
    assert seen == ["What's my brand voice?", "Warm and witty.", "Make it more formal"]


def test_no_tool_can_publish() -> None:
    assert_no_outbound()
    assert not any(t.outbound for t in TOOLS.values())
    forbidden = ("publish", "send", "post_")
    assert not [n for n in TOOLS if n.startswith(forbidden)]
