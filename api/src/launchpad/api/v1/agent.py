"""Agent runs. The API never executes graphs: it records the request, enqueues a durable job and
streams the run's event log. That's why an API restart can't break a run, and why any client can
(re)attach to a run's stream at any point and replay it from the start or from Last-Event-ID."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from launchpad.agent.runner import TERMINAL, Recorder, usage_payload
from launchpad.api.deps import DB, CurrentUser, CurrentWorkspace
from launchpad.api.errors import Conflict, NotFound
from launchpad.api.ratelimit import rate_limit
from launchpad.config import get_settings
from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import AgentRunStatus, JobKind
from launchpad.jobs.queue import enqueue
from launchpad.models import AgentEvent, AgentRun, Campaign, Workspace
from launchpad.schemas.agent import EventOut, ResumeIn, RunCreateIn, RunDetailOut, RunOut

router = APIRouter(prefix="/workspaces/{workspace_id}/agent", tags=["agent"])

POLL_S = 0.5
KEEPALIVE_S = 15.0
MAX_STREAM_S = 30 * 60  # EventSource reconnects with Last-Event-ID after this
ACTIVE = (AgentRunStatus.RUNNING, AgentRunStatus.AWAITING_APPROVAL)


async def _run(db: DB, ws: Workspace, run_id: uuid.UUID) -> AgentRun:
    run = await db.get(AgentRun, run_id)
    if run is None or run.workspace_id != ws.id:
        raise NotFound("Run not found.")
    return run


@router.post(
    "/runs",
    response_model=RunOut,
    status_code=201,
    dependencies=[Depends(rate_limit("agent_run", 10, 60))],
)
async def create_run(body: RunCreateIn, ws: CurrentWorkspace, user: CurrentUser, db: DB) -> RunOut:
    if body.campaign_id:
        campaign = await db.get(Campaign, body.campaign_id)
        if campaign is None or campaign.workspace_id != ws.id:
            raise NotFound("Campaign not found.")
    thread_id = body.thread_id or f"t_{secrets.token_urlsafe(12)}"
    if body.thread_id:
        owner = await db.scalar(
            select(AgentRun.workspace_id).where(AgentRun.thread_id == thread_id).limit(1)
        )
        if owner is None or owner != ws.id:
            raise NotFound("Conversation not found.")
        busy = await db.scalar(
            select(AgentRun.status)
            .where(AgentRun.thread_id == thread_id, AgentRun.status.in_(ACTIVE))
            .limit(1)
        )
        if busy is not None:
            raise Conflict(
                "This conversation already has a run in progress."
                if busy == AgentRunStatus.RUNNING
                else "Review the drafts waiting for approval (or stop that run) first."
            )
    s = get_settings()
    run = AgentRun(
        workspace_id=ws.id,
        user_id=user.id,
        campaign_id=body.campaign_id,
        thread_id=thread_id,
        title=body.message[:80],
        input=body.message,
        status=AgentRunStatus.RUNNING,
        token_budget=s.agent_run_token_budget,
        cost_budget_usd=s.agent_run_cost_budget_usd,
    )
    db.add(run)
    await db.commit()
    await enqueue(db, workspace_id=ws.id, kind=JobKind.AGENT_RUN, payload={"run_id": str(run.id)})
    await db.refresh(run)
    return RunOut.model_validate(run)


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    ws: CurrentWorkspace,
    db: DB,
    thread_id: str | None = None,
    limit: int = Query(default=30, le=100),
) -> list[RunOut]:
    q = select(AgentRun).where(AgentRun.workspace_id == ws.id)
    if thread_id:
        q = q.where(AgentRun.thread_id == thread_id)
    rows = await db.scalars(q.order_by(AgentRun.created_at.desc()).limit(limit))
    return [RunOut.model_validate(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: uuid.UUID, ws: CurrentWorkspace, db: DB) -> RunDetailOut:
    run = await _run(db, ws, run_id)
    events = await db.scalars(
        select(AgentEvent).where(AgentEvent.run_id == run.id).order_by(AgentEvent.seq)
    )
    out = RunDetailOut.model_validate({**RunOut.model_validate(run).model_dump(), "events": []})
    out.events = [EventOut.model_validate(e) for e in events]
    return out


def _sse(e: AgentEvent) -> bytes:
    data = json.dumps(e.data, default=str, ensure_ascii=False)
    return f"id: {e.seq}\nevent: {e.type}\ndata: {data}\n\n".encode()


@router.get(
    "/runs/{run_id}/stream",
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-sent events"}},
)
async def stream_run(
    run_id: uuid.UUID,
    ws: CurrentWorkspace,
    db: DB,
    after: int = Query(default=0, ge=0, description="Replay events with seq greater than this"),
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    """Replays the run's events, then follows live ones. Event types are documented in the
    README. Ends after `run_finished`, or when the run is over and nothing new arrives."""
    await _run(db, ws, run_id)
    cursor = after
    if last_event_id and last_event_id.isdigit():
        cursor = max(cursor, int(last_event_id))

    async def events() -> AsyncIterator[bytes]:
        nonlocal cursor
        started = last_sent = time.monotonic()
        idle_terminal = 0
        while time.monotonic() - started < MAX_STREAM_S:
            async with get_sessionmaker()() as session:
                rows = list(
                    await session.scalars(
                        select(AgentEvent)
                        .where(AgentEvent.run_id == run_id, AgentEvent.seq > cursor)
                        .order_by(AgentEvent.seq)
                        .limit(200)
                    )
                )
                status = await session.scalar(select(AgentRun.status).where(AgentRun.id == run_id))
            for e in rows:
                cursor = e.seq
                yield _sse(e)
                last_sent = time.monotonic()
                if e.type == "run_finished":
                    return
            if not rows and status in TERMINAL:
                idle_terminal += 1
                if idle_terminal >= 3:  # finished (e.g. cancelled before it started)
                    return
            else:
                idle_terminal = 0
            if time.monotonic() - last_sent >= KEEPALIVE_S:
                yield b": keep-alive\n\n"
                last_sent = time.monotonic()
            if not rows:
                await asyncio.sleep(POLL_S)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache, no-transform", "x-accel-buffering": "no"},
    )


@router.post(
    "/runs/{run_id}/resume",
    response_model=RunOut,
    dependencies=[Depends(rate_limit("agent_run", 10, 60))],
)
async def resume_run(run_id: uuid.UUID, body: ResumeIn, ws: CurrentWorkspace, db: DB) -> RunOut:
    """Apply the user's approve / edit / reject decisions and let the run finish."""
    run = await _run(db, ws, run_id)
    if run.status != AgentRunStatus.AWAITING_APPROVAL:
        raise Conflict(f"This run is {run.status.value}, not waiting for approval.")
    run.status = AgentRunStatus.RUNNING  # claims the resume; a double-submit gets a 409
    await db.commit()
    decisions: list[dict[str, Any]] = [d.model_dump(mode="json") for d in body.decisions]
    await enqueue(
        db,
        workspace_id=ws.id,
        kind=JobKind.AGENT_RUN,
        payload={"run_id": str(run.id), "decisions": decisions},
    )
    await db.refresh(run)
    return RunOut.model_validate(run)


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: uuid.UUID, ws: CurrentWorkspace, db: DB) -> RunOut:
    """Stops a run. A running graph notices before its next LLM or tool call. Drafts it already
    created stay as drafts."""
    run = await _run(db, ws, run_id)
    if run.status in TERMINAL:
        return RunOut.model_validate(run)
    was_waiting = run.status == AgentRunStatus.AWAITING_APPROVAL
    run.status = AgentRunStatus.CANCELLED
    if was_waiting:  # nothing is executing, so record the end here
        run.finished_at = datetime.now(UTC)
        run.final = run.final or "Stopped."
    await db.commit()
    if was_waiting:
        usage = await usage_payload(db, run)
        await Recorder(run.id).emit("run_finished", {"status": "cancelled", **usage})
    await db.refresh(run)
    return RunOut.model_validate(run)
