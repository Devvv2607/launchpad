"""The orchestrator graph.

    START → planner ─┬→ END (refused)
                     └→ agent ─┬→ tools → reflect ─┬→ agent          (continue)
                               │                   └→ approval|END   (cap / budget / plan done)
                               └→ approval (drafts to review) → END
                                  └ interrupt(): resumes with the user's decisions

State holds plain JSON so the Postgres checkpointer can persist it after every node; a run
interrupted by a crash or restart continues from the last completed node. Runtime-only objects
(DB sessions, event emitter, cancellation check) come from `runtime.context` and are never
checkpointed.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, TypedDict
from zoneinfo import ZoneInfo

import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from launchpad.agent.tools import TOOLS, ToolContext, assert_no_outbound
from launchpad.content.engine import main_text, parse_content, revalidate
from launchpad.domain.enums import Channel, ContentStatus
from launchpad.llm.service import CallContext, LLMService
from launchpad.llm.types import LLMResult, Message, Purpose, ToolCall, ToolSpec
from launchpad.models import AgentRun, ContentItem, LLMCall, Workspace
from launchpad.prompts import load_prompt

log = structlog.get_logger(__name__)

MAX_RESULT_CHARS = 6000  # what the model sees of a tool result
MAX_DISPLAY_CHARS = 1500  # what the UI timeline stores


class RunCancelled(Exception):
    pass


class AgentState(TypedDict, total=False):
    workspace_id: str
    run_id: str
    user_id: str | None
    messages: list[dict[str, Any]]
    plan: dict[str, Any] | None
    status: str  # running | refused | finished | budget_exceeded | tool_cap | awaiting_approval
    pending_approvals: list[str]
    produced_item_ids: list[str]
    tool_calls_used: int
    notes: list[str]
    errors: list[str]
    final: str | None


@dataclass
class AgentDeps:
    sessions: async_sessionmaker[AsyncSession]
    llm: LLMService
    emit: Callable[[str, dict[str, Any]], Awaitable[None]]
    is_cancelled: Callable[[], Awaitable[bool]]
    max_tool_calls: int
    token_budget: int
    cost_budget_usd: Decimal


Rt = Runtime[AgentDeps]


# ------------------------------------------------------------------ helpers


def to_msg(d: dict[str, Any]) -> Message:
    return Message(
        role=d["role"],
        content=d.get("content") or "",
        tool_calls=[ToolCall(**c) for c in d.get("tool_calls") or []],
        tool_call_id=d.get("tool_call_id"),
        name=d.get("name"),
    )


def from_msg(m: Message) -> dict[str, Any]:
    return {
        "role": m.role,
        "content": m.content,
        "tool_calls": [c.__dict__ for c in m.tool_calls],
        "tool_call_id": m.tool_call_id,
        "name": m.name,
    }


def _short(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"… [{len(text) - limit} more characters]"


async def _guard(rt: Rt) -> None:
    if await rt.context.is_cancelled():
        raise RunCancelled()


async def _context(db: AsyncSession, state: AgentState) -> tuple[Workspace, CallContext]:
    ws = await db.get(Workspace, uuid.UUID(state["workspace_id"]))
    assert ws is not None
    user = uuid.UUID(state["user_id"]) if state.get("user_id") else None
    return ws, CallContext.for_workspace(ws, user, run_id=uuid.UUID(state["run_id"]))


async def run_usage(db: AsyncSession, run_id: str) -> tuple[int, Decimal]:
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(LLMCall.tokens_in + LLMCall.tokens_out), 0),
                func.coalesce(func.sum(LLMCall.cost_usd), 0),
            ).where(LLMCall.run_id == uuid.UUID(run_id))
        )
    ).one()
    return int(row[0]), Decimal(row[1] or 0)


def _today(ws: Workspace) -> str:
    now = datetime.now(ZoneInfo(ws.timezone))
    return f"{now.date().isoformat()} ({now.strftime('%A')})"


# ------------------------------------------------------------------ planner


class PlanStep(BaseModel):
    title: str = Field(description="What this step does, for the user")
    tool: str = Field(description="One tool name from the list, or 'respond'")


class PlanOut(BaseModel):
    model_config = {"extra": "forbid"}
    intent: Literal["on_topic", "off_topic", "harmful"]
    refusal: str | None = Field(default=None, description="Friendly reply when not on_topic")
    goal: str = Field(default="", description="The user's goal in one sentence")
    steps: list[PlanStep] = Field(default_factory=list, max_length=8)


async def planner(state: AgentState, runtime: Rt) -> dict[str, Any]:
    await _guard(runtime)
    deps = runtime.context
    await deps.emit("step_started", {"key": "plan", "label": "Planning"})
    async with deps.sessions() as db:
        ws, ctx = await _context(db, state)
        history = [
            {"role": m["role"], "content": _short(m.get("content") or "", 1200)}
            for m in state["messages"]
            if m["role"] in ("user", "assistant") and m.get("content")
        ][-12:]
        prompt = load_prompt("agent_planner").render(
            business_name=ws.name,
            industry=ws.industry.value,
            locations=list(ws.locations or []),
            today=_today(ws),
            timezone=ws.timezone,
            history=history,
            tools=[{"name": t.name, "description": t.description} for t in TOOLS.values()],
        )
        result, _ = await deps.llm.generate(
            ctx, Purpose.PLANNING, prompt, task="agent_plan", schema=PlanOut, temperature=0.2
        )
    plan = result.parsed
    assert plan is not None
    if plan.intent != "on_topic":
        reply = (
            plan.refusal
            or "I can help with marketing for your business: content, campaigns and research."
        )
        await deps.emit("plan", {"refused": True, "intent": plan.intent, "reply": reply})
        return {
            "status": "refused",
            "final": reply,
            "plan": None,
            "messages": [*state["messages"], {"role": "assistant", "content": reply}],
        }
    valid = {*TOOLS, "respond"}
    steps = [
        {
            "id": i + 1,
            "title": s.title,
            "tool": s.tool if s.tool in valid else "respond",
            "status": "pending",
        }
        for i, s in enumerate(plan.steps)
    ] or [{"id": 1, "title": "Answer the request", "tool": "respond", "status": "pending"}]
    data = {"goal": plan.goal, "steps": steps}
    await deps.emit("plan", data)
    return {"plan": data, "status": "running"}


# ------------------------------------------------------------------ agent


async def agent(state: AgentState, runtime: Rt) -> dict[str, Any]:
    await _guard(runtime)
    deps = runtime.context
    async with deps.sessions() as db:
        tokens, cost = await run_usage(db, state["run_id"])
        if tokens >= deps.token_budget or cost >= deps.cost_budget_usd:
            return _stop(
                state,
                "budget_exceeded",
                f"I stopped because this run reached its budget ({tokens:,} tokens, ${cost:.4f}).",
            )
        ws, ctx = await _context(db, state)
        system = load_prompt("agent_system").render(
            business_name=ws.name,
            industry=ws.industry.value,
            locations=list(ws.locations or []),
            today=_today(ws),
            timezone=ws.timezone,
            plan=state.get("plan") or {"goal": "", "steps": []},
            notes=state.get("notes") or [],
        )
        specs = [
            ToolSpec(t.name, t.description, t.input_model.model_json_schema())
            for t in TOOLS.values()
        ]
        messages = [Message("system", system.system), *(to_msg(m) for m in state["messages"])]
        await deps.emit(
            "step_started", {"key": f"think_{len(state['messages'])}", "label": "Thinking"}
        )
        result: LLMResult[BaseModel]
        result, _ = await deps.llm.generate(
            ctx,
            Purpose.PLANNING,
            messages=messages,
            task="agent_step",
            tools=specs,
            temperature=0.4,
            max_tokens=4096,
        )
    msg = Message("assistant", result.text, tool_calls=result.tool_calls)
    if result.text:
        await deps.emit("token", {"text": result.text, "final": not result.tool_calls})
    update: dict[str, Any] = {"messages": [*state["messages"], from_msg(msg)], "notes": []}
    if not result.tool_calls:
        update["final"] = result.text
        update["status"] = "finished"
        update["plan"] = _mark_respond_done(state.get("plan"))
        if update["plan"]:
            await deps.emit("plan", update["plan"])
    return update


def _mark_respond_done(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not plan:
        return plan
    steps = [
        dict(s, status="done") if s["tool"] == "respond" and s["status"] == "pending" else s
        for s in plan["steps"]
    ]
    return {**plan, "steps": steps}


def _stop(state: AgentState, status: str, reply: str) -> dict[str, Any]:
    return {
        "status": status,
        "final": reply,
        "messages": [*state["messages"], {"role": "assistant", "content": reply}],
    }


def route_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if last.get("tool_calls") and state.get("status") == "running":
        return "tools"
    return "approval" if state.get("pending_approvals") else END


# ------------------------------------------------------------------ tools


async def tools(state: AgentState, runtime: Rt) -> dict[str, Any]:
    deps = runtime.context
    assert_no_outbound()
    calls = state["messages"][-1].get("tool_calls") or []
    used = state.get("tool_calls_used", 0)
    messages = list(state["messages"])
    produced = list(state.get("produced_item_ids") or [])
    pending = list(state.get("pending_approvals") or [])
    errors = list(state.get("errors") or [])
    executed: list[tuple[str, bool]] = []
    async with deps.sessions() as db:
        ws, ctx = await _context(db, state)
        for call in calls:
            await _guard(runtime)
            name, call_id = call["name"], call["id"]
            if used >= deps.max_tool_calls:
                messages.append(
                    _tool_msg(
                        call_id,
                        name,
                        {
                            "error": f"Tool-call limit ({deps.max_tool_calls}) reached for "
                            "this run. Stop and summarise."
                        },
                    )
                )
                executed.append((name, False))
                continue
            used += 1
            tool = TOOLS.get(name)
            await deps.emit(
                "tool_call", {"id": call_id, "tool": name, "input": call.get("arguments") or {}}
            )
            if tool is None:
                out: dict[str, Any] = {
                    "error": f"Unknown tool '{name}'. Use one of: {', '.join(TOOLS)}."
                }
                ok = False
            else:
                await deps.emit(
                    "step_started", {"key": call_id, "label": f"{tool.progress_label}…"}
                )
                started = time.perf_counter()
                tc = ToolContext(
                    db=db, ws=ws, ctx=ctx, run_id=uuid.UUID(state["run_id"]), emit=deps.emit
                )
                try:
                    args = tool.input_model.model_validate(call.get("arguments") or {})
                    out = await tool.handler(tc, args)
                    ok = "error" not in out
                except ValidationError as exc:
                    await db.rollback()
                    out = {
                        "error": "Invalid arguments: "
                        + "; ".join(
                            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
                        )
                    }
                    ok = False
                except RunCancelled:
                    raise
                except Exception as exc:
                    await db.rollback()
                    log.warning("agent_tool_failed", tool=name, error=str(exc))
                    out = {"error": f"{type(exc).__name__}: {exc}"[:500]}
                    ok = False
                produced += tc.created_item_ids
                pending += tc.created_item_ids
                await deps.emit(
                    "tool_result",
                    {
                        "id": call_id,
                        "tool": name,
                        "ok": ok,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                        "output": _short(out, MAX_DISPLAY_CHARS),
                    },
                )
            if not ok:
                errors.append(f"{name}: {out.get('error')}")
            executed.append((name, ok))
            messages.append(_tool_msg(call_id, name, out))
        run = await db.get(AgentRun, uuid.UUID(state["run_id"]))
        if run is not None:
            run.tool_calls = used
            await db.commit()
    return {
        "messages": messages,
        "tool_calls_used": used,
        "produced_item_ids": produced,
        "pending_approvals": pending,
        "errors": errors,
        "notes": [f"{n} {'succeeded' if ok else 'failed'}" for n, ok in executed],
        "plan": _advance_plan(state.get("plan"), executed),
    }


def _tool_msg(call_id: str, name: str, out: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "content": _short(out, MAX_RESULT_CHARS),
        "tool_call_id": call_id,
        "name": name,
    }


def _advance_plan(
    plan: dict[str, Any] | None, executed: list[tuple[str, bool]]
) -> dict[str, Any] | None:
    if not plan:
        return plan
    steps = [dict(s) for s in plan["steps"]]
    for name, ok in executed:
        for s in steps:
            if s["tool"] == name and s["status"] in ("pending", "failed"):
                s["status"] = "done" if ok else "failed"
                break
    return {**plan, "steps": steps}


# ------------------------------------------------------------------ reflect


async def reflect(state: AgentState, runtime: Rt) -> dict[str, Any]:
    """Check progress against the plan; continue, steer, or stop."""
    deps = runtime.context
    plan = state.get("plan")
    if plan:
        await deps.emit("plan", plan)
    notes = list(state.get("notes") or [])
    if state.get("tool_calls_used", 0) >= deps.max_tool_calls:
        return {
            **_stop(
                state,
                "tool_cap",
                f"I stopped after {deps.max_tool_calls} tool calls (this run's limit). "
                f"Here's where things stand: {_progress(plan)}",
            ),
            "notes": notes,
        }
    async with deps.sessions() as db:
        tokens, cost = await run_usage(db, state["run_id"])
    if tokens >= deps.token_budget or cost >= deps.cost_budget_usd:
        return {
            **_stop(
                state,
                "budget_exceeded",
                f"I stopped because this run reached its budget "
                f"({tokens:,} tokens, ${cost:.4f}). {_progress(plan)}",
            ),
            "notes": notes,
        }
    if plan:
        failed_twice = [
            s
            for s in plan["steps"]
            if s["status"] == "failed"
            and sum(1 for e in state.get("errors", []) if e.startswith(s["tool"] + ":")) >= 2
        ]
        for s in failed_twice:
            notes.append(f"Step '{s['title']}' failed twice; skip it and tell the user why.")
        remaining = [
            s for s in plan["steps"] if s["status"] == "pending" and s["tool"] != "respond"
        ]
        notes.append(
            "Remaining steps: "
            + (
                "; ".join(s["title"] for s in remaining)
                if remaining
                else "none — reply to the user now."
            )
        )
    return {"notes": notes}


def _progress(plan: dict[str, Any] | None) -> str:
    if not plan:
        return ""
    done = [s["title"] for s in plan["steps"] if s["status"] == "done"]
    return ("Completed: " + "; ".join(done) + ".") if done else "No steps were completed."


def route_reflect(state: AgentState) -> str:
    if state.get("status") in ("tool_cap", "budget_exceeded"):
        return "approval" if state.get("pending_approvals") else END
    return "agent"


# ------------------------------------------------------------------ approval


class Decision(BaseModel):
    item_id: uuid.UUID
    action: Literal["approve", "reject", "edit"]
    content: dict[str, Any] | None = None  # for "edit": full structured content


async def approval(state: AgentState, runtime: Rt) -> dict[str, Any]:
    deps = runtime.context
    pending = list(state.get("pending_approvals") or [])
    async with deps.sessions() as db:
        rows = await db.scalars(
            select(ContentItem).where(ContentItem.id.in_([uuid.UUID(i) for i in pending]))
        )
        items = [
            {
                "item_id": str(r.id),
                "channel": r.channel.value,
                "label": r.variant_label,
                "angle": r.title,
                "preview": r.body[:280],
                "blocked": any(
                    v.get("severity") == "error" for v in (r.generation or {}).get("violations", [])
                ),
            }
            for r in rows
        ]
    # Pauses the graph; the checkpointer persists state. Resumes with the user's decisions.
    raw = interrupt({"type": "approval_required", "items": items})
    decisions = [Decision.model_validate(d) for d in (raw or [])]
    summary: dict[str, int] = {"approved": 0, "rejected": 0, "edited": 0, "skipped": 0}
    async with deps.sessions() as db:
        ws, _ = await _context(db, state)
        for d in decisions:
            item = await db.get(ContentItem, d.item_id)
            if item is None or item.workspace_id != ws.id or str(d.item_id) not in pending:
                summary["skipped"] += 1
                continue
            if d.action == "reject":
                item.status = ContentStatus.REJECTED
                summary["rejected"] += 1
                continue
            if d.action == "edit" and d.content is not None:
                content = parse_content(Channel(item.channel), d.content).model_dump()
                violations = revalidate(Channel(item.channel), content)
                keep = (
                    {"rendered": item.payload["rendered"]}
                    if "rendered" in (item.payload or {})
                    else {}
                )
                item.payload = {**content, **keep}
                item.body = main_text(Channel(item.channel), content)
                item.hashtags = list(content.get("hashtags", []))
                item.generation = {
                    **(item.generation or {}),
                    "violations": violations,
                    "edited": True,
                }
                summary["edited"] += 1
            if any(
                v.get("severity") == "error" for v in (item.generation or {}).get("violations", [])
            ):
                summary["skipped"] += 1  # can't approve content that breaks a platform limit
                continue
            # Approval is applied only from an explicit human decision, never by the model.
            item.status = ContentStatus.APPROVED
            item.approved_by = uuid.UUID(state["user_id"]) if state.get("user_id") else None
            item.approved_at = datetime.now(ZoneInfo("UTC"))
            summary["approved"] += 1
        await db.commit()
    decided = {str(d.item_id) for d in decisions}
    await deps.emit("approvals_applied", summary)
    note = (
        f"The user reviewed the drafts: {summary['approved']} approved, "
        f"{summary['rejected']} rejected, {summary['edited']} edited."
    )
    return {
        "pending_approvals": [i for i in pending if i not in decided],
        "messages": [*state["messages"], {"role": "user", "content": f"[system note] {note}"}],
        "status": "finished",
    }


# ------------------------------------------------------------------ build


def build_graph() -> StateGraph[AgentState, AgentDeps, AgentState, AgentState]:
    g: StateGraph[AgentState, AgentDeps, AgentState, AgentState] = StateGraph(
        AgentState, context_schema=AgentDeps
    )
    g.add_node("planner", planner)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_node("reflect", reflect)
    g.add_node("approval", approval)
    g.add_edge(START, "planner")
    g.add_conditional_edges(
        "planner", lambda s: END if s.get("status") == "refused" else "agent", ["agent", END]
    )
    g.add_conditional_edges("agent", route_agent, ["tools", "approval", END])
    g.add_edge("tools", "reflect")
    g.add_conditional_edges("reflect", route_reflect, ["agent", "approval", END])
    g.add_edge("approval", END)
    return g
