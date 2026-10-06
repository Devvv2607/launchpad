"""Executes agent runs (in the worker) and records every step.

Durability: the graph checkpoints to Postgres after each node. If the worker dies mid-run, the
job is re-claimed and `execute_run` continues from the last checkpoint instead of starting over.
The API never runs graphs, so restarting the API doesn't affect a run at all; clients just
reconnect to the event stream, which replays from `agent_events`.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.agent.graph import AgentDeps, RunCancelled, build_graph, run_usage
from launchpad.config import get_settings
from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import AgentRunStatus, MessageRole
from launchpad.llm.errors import LLMError
from launchpad.llm.service import LLMService, llm
from launchpad.models import AgentEvent, AgentMessage, AgentRun, LLMCall

log = structlog.get_logger(__name__)

TERMINAL = {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}
_saver_ready = False


def checkpointer_url() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


@asynccontextmanager
async def checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    global _saver_ready
    if sys.platform == "win32":  # psycopg async can't use the Proactor loop
        import asyncio

        if isinstance(asyncio.get_running_loop(), asyncio.ProactorEventLoop):
            raise RuntimeError(
                "Run the worker with WindowsSelectorEventLoopPolicy (psycopg requirement)."
            )
    async with AsyncPostgresSaver.from_conn_string(checkpointer_url()) as saver:
        if not _saver_ready:
            await saver.setup()  # creates/migrates LangGraph's own tables (idempotent)
            _saver_ready = True
        yield saver


class Recorder:
    """Appends ordered events (for the stream) and trace rows (for history)."""

    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        self._seq: int | None = None
        self._msg_seq: int | None = None

    async def emit(self, type_: str, data: dict[str, Any]) -> None:
        async with get_sessionmaker()() as db:
            if self._seq is None:
                self._seq = int(
                    await db.scalar(
                        select(func.coalesce(func.max(AgentEvent.seq), 0)).where(
                            AgentEvent.run_id == self.run_id
                        )
                    )
                    or 0
                )
            if self._msg_seq is None:
                self._msg_seq = int(
                    await db.scalar(
                        select(func.coalesce(func.max(AgentMessage.seq), 0)).where(
                            AgentMessage.run_id == self.run_id
                        )
                    )
                    or 0
                )
            self._seq += 1
            db.add(AgentEvent(run_id=self.run_id, seq=self._seq, type=type_, data=data))
            trace = self._trace(type_, data)
            if trace is not None:
                self._msg_seq += 1
                trace.seq = self._msg_seq
                db.add(trace)
            await db.commit()

    def _trace(self, type_: str, data: dict[str, Any]) -> AgentMessage | None:
        if type_ == "tool_call":
            return AgentMessage(
                run_id=self.run_id,
                seq=0,
                role=MessageRole.TOOL,
                tool_name=data["tool"],
                tool_call_id=data["id"],
                tool_input=data.get("input"),
            )
        if type_ == "tool_result":
            return AgentMessage(
                run_id=self.run_id,
                seq=0,
                role=MessageRole.TOOL,
                tool_name=data["tool"],
                tool_call_id=data["id"],
                tool_output={"ok": data.get("ok"), "output": data.get("output")},
                latency_ms=data.get("duration_ms"),
                error=None if data.get("ok") else str(data.get("output"))[:2000],
            )
        if type_ == "token" and data.get("text"):
            return AgentMessage(
                run_id=self.run_id, seq=0, role=MessageRole.ASSISTANT, content=data["text"]
            )
        if type_ == "plan":
            return AgentMessage(
                run_id=self.run_id, seq=0, role=MessageRole.SYSTEM, content="plan", tool_output=data
            )
        return None


async def _is_cancelled(run_id: uuid.UUID) -> bool:
    async with get_sessionmaker()() as db:
        status = await db.scalar(select(AgentRun.status).where(AgentRun.id == run_id))
    return status == AgentRunStatus.CANCELLED


async def usage_payload(db: AsyncSession, run: AgentRun) -> dict[str, Any]:
    """Usage for run_finished. `cost_complete` is false when any call used a model with no known
    price, so the UI says "unknown" instead of showing a made-up $0."""
    unpriced = await db.scalar(
        select(func.count()).where(
            LLMCall.run_id == run.id, LLMCall.status == "ok", LLMCall.cost_usd.is_(None)
        )
    )
    return {"cost_usd": str(run.cost_usd), "cost_complete": not unpriced, "tokens": run.tokens_in}


async def _finish(
    run_id: uuid.UUID, status: AgentRunStatus, *, final: str | None = None, error: str | None = None
) -> tuple[AgentRun, dict[str, Any]]:
    """Records the run's end state; returns the run and its usage for the run_finished event."""
    async with get_sessionmaker()() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None
        if run.status == AgentRunStatus.CANCELLED and status != AgentRunStatus.CANCELLED:
            status = AgentRunStatus.CANCELLED  # a cancel wins over a late completion
        tokens, cost = await run_usage(db, str(run_id))
        run.status, run.tokens_in, run.cost_usd = status, tokens, cost
        if final is not None:
            run.final = final
        if error is not None:
            run.error = error[:2000]
        if status in TERMINAL:
            run.finished_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(run)
        return run, await usage_payload(db, run)


async def execute_run(
    run_id: uuid.UUID,
    *,
    decisions: list[dict[str, Any]] | None = None,
    service: LLMService | None = None,
) -> AgentRunStatus:
    async with get_sessionmaker()() as db:
        run = await db.get(AgentRun, run_id)
        if run is None:
            return AgentRunStatus.FAILED
        if run.status in TERMINAL:
            return run.status
        thread_id, user_id, workspace_id, message = (
            run.thread_id,
            run.user_id,
            run.workspace_id,
            run.input,
        )
        cost_budget = run.cost_budget_usd
        token_budget = run.token_budget

    s = get_settings()
    rec = Recorder(run_id)
    deps = AgentDeps(
        sessions=get_sessionmaker(),
        llm=service or llm,
        emit=rec.emit,
        is_cancelled=lambda: _is_cancelled(run_id),
        max_tool_calls=s.agent_max_tool_calls,
        token_budget=token_budget,
        cost_budget_usd=Decimal(cost_budget),
    )
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    async with checkpointer() as saver:
        graph = build_graph().compile(checkpointer=saver)
        snap = await graph.aget_state(config)
        values = snap.values if snap else {}
        inp: Any  # AgentState | Command | None; built as a plain dict below
        if decisions is not None:
            inp = Command(resume=decisions)
            async with get_sessionmaker()() as db:
                r = await db.get(AgentRun, run_id)
                assert r is not None
                r.status = AgentRunStatus.RUNNING
                await db.commit()
        elif snap and snap.next and values.get("run_id") == str(run_id):
            inp = None  # recovering this run after a crash: continue from the last checkpoint
            await rec.emit(
                "step_started", {"key": "recover", "label": "Resuming after an interruption"}
            )
        else:
            history = list(values.get("messages") or [])
            inp = {
                "workspace_id": str(workspace_id),
                "run_id": str(run_id),
                "user_id": str(user_id) if user_id else None,
                "messages": [*history, {"role": "user", "content": message or ""}],
                "plan": None,
                "status": "running",
                "pending_approvals": [],
                "produced_item_ids": [],
                "tool_calls_used": 0,
                "notes": [],
                "errors": [],
                "final": None,
            }
            await rec.emit(
                "run_started", {"run_id": str(run_id), "thread_id": thread_id, "message": message}
            )
        try:
            out = await graph.ainvoke(inp, config, context=deps)
        except RunCancelled:
            _, usage = await _finish(run_id, AgentRunStatus.CANCELLED, final="Stopped.")
            await rec.emit("run_finished", {"status": "cancelled", **usage})
            return AgentRunStatus.CANCELLED
        except LLMError as exc:
            _, usage = await _finish(run_id, AgentRunStatus.FAILED, error=exc.message)
            await rec.emit(
                "error",
                {
                    "code": exc.code,
                    "message": exc.message,
                    "hint": exc.hint,
                    "provider": exc.provider,
                    "model": exc.model,
                },
            )
            await rec.emit("run_finished", {"status": "failed", **usage})
            return AgentRunStatus.FAILED
        except Exception as exc:
            log.exception("agent_run_crashed", run_id=str(run_id))
            _, usage = await _finish(
                run_id, AgentRunStatus.FAILED, error=f"{type(exc).__name__}: {exc}"
            )
            await rec.emit(
                "error",
                {
                    "code": "internal_error",
                    "message": "The agent hit an unexpected error.",
                    "hint": "Try again; if it repeats, share the run id.",
                },
            )
            await rec.emit("run_finished", {"status": "failed", **usage})
            return AgentRunStatus.FAILED

    interrupts = out.get("__interrupt__") or []
    if interrupts:
        payload = interrupts[0].value
        await _finish(run_id, AgentRunStatus.AWAITING_APPROVAL, final=out.get("final"))
        await rec.emit(
            "approval_required", {"items": payload.get("items", []), "final": out.get("final")}
        )
        return AgentRunStatus.AWAITING_APPROVAL
    _, usage = await _finish(run_id, AgentRunStatus.COMPLETED, final=out.get("final"))
    await rec.emit(
        "run_finished",
        {
            "status": out.get("status") or "finished",
            "final": out.get("final"),
            "item_ids": out.get("produced_item_ids") or [],
            **usage,
        },
    )
    return AgentRunStatus.COMPLETED
