"""Agent run endpoints: the API records runs and streams their event log; the worker runs them.
Here `execute_run` stands in for the worker, using the scripted LLM."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from launchpad.agent.runner import execute_run
from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import JobKind
from launchpad.models import ScheduledJob
from tests.agent.fake_agent import AgentLLM, plan, reply, tools
from tests.agent.test_graph import WRITE_IG, svc
from tests.agent.test_graph import env as env
from tests.agent.test_graph import fake_provider as fake_provider

pytestmark = pytest.mark.usefixtures("env", "fake_provider")


async def _ws(client: AsyncClient) -> str:
    r = await client.post(
        "/api/v1/workspaces",
        json={"name": "Brew Lab", "industry": "food", "locations": ["Mumbai"]},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _sse(text: str) -> list[tuple[int, str, dict[str, Any]]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln and not ln.startswith(":")]
        fields = dict(ln.split(": ", 1) for ln in lines)
        if "data" in fields:
            out.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return out


def _fake() -> AgentLLM:
    return AgentLLM(
        planner=plan(("Write drafts", "write_content"), ("Summarise", "respond")),
        turns=[tools(WRITE_IG), reply("Two drafts are ready for review.")],
    )


async def _start(client: AsyncClient, ws: str, message: str = "Write posts") -> dict[str, Any]:
    r = await client.post(f"/api/v1/workspaces/{ws}/agent/runs", json={"message": message})
    assert r.status_code == 201, r.text
    return dict(r.json())


async def test_create_enqueues_a_durable_job_and_rejects_parallel_runs(
    authed: AsyncClient,
) -> None:
    ws = await _ws(authed)
    run = await _start(authed, ws, "Plan a launch")
    assert run["status"] == "running" and run["thread_id"].startswith("t_")
    async with get_sessionmaker()() as db:
        job = await db.scalar(select(ScheduledJob).where(ScheduledJob.kind == JobKind.AGENT_RUN))
    assert job is not None and job.payload == {"run_id": run["id"]}

    again = await authed.post(
        f"/api/v1/workspaces/{ws}/agent/runs",
        json={"message": "And another", "thread_id": run["thread_id"]},
    )
    assert again.status_code == 409
    unknown = await authed.post(
        f"/api/v1/workspaces/{ws}/agent/runs", json={"message": "hello", "thread_id": "t_nope"}
    )
    assert unknown.status_code == 404


async def test_resume_once_then_reconnect_from_last_event_id(authed: AsyncClient) -> None:
    ws = await _ws(authed)
    run = await _start(authed, ws)
    base = f"/api/v1/workspaces/{ws}/agent/runs/{run['id']}"
    await execute_run(uuid.UUID(run["id"]), service=svc(_fake()))  # the worker's job

    # Paused for approval (a live stream would stay open), so read the stored log.
    detail = (await authed.get(base)).json()
    assert detail["status"] == "awaiting_approval"
    assert detail["events"][0]["type"] == "run_started"
    assert detail["events"][-1]["type"] == "approval_required"
    items = detail["events"][-1]["data"]["items"]
    paused_at = detail["events"][-1]["seq"]

    assert (await authed.post(f"{base}/resume", json={"decisions": []})).status_code == 422
    decisions = [{"item_id": items[0]["item_id"], "action": "approve"}]
    r = await authed.post(f"{base}/resume", json={"decisions": decisions})
    assert r.status_code == 200 and r.json()["status"] == "running"
    twice = await authed.post(f"{base}/resume", json={"decisions": decisions})
    assert twice.status_code == 409  # a double submit can't resume twice

    async with get_sessionmaker()() as db:
        jobs = (
            await db.scalars(
                select(ScheduledJob)
                .where(ScheduledJob.kind == JobKind.AGENT_RUN)
                .order_by(ScheduledJob.created_at)
            )
        ).all()
    assert jobs[-1].payload["decisions"][0]["action"] == "approve"
    await execute_run(
        uuid.UUID(run["id"]), decisions=jobs[-1].payload["decisions"], service=svc(_fake())
    )

    # A reconnecting client gets only what it missed, ending at run_finished.
    s = await authed.get(f"{base}/stream", headers={"last-event-id": str(paused_at)})
    assert s.status_code == 200
    assert s.headers["content-type"].startswith("text/event-stream")
    missed = _sse(s.text)
    assert missed[0][0] == paused_at + 1
    assert missed[-1][1] == "run_finished" and missed[-1][2]["status"] == "finished"

    full = _sse((await authed.get(f"{base}/stream")).text)
    assert [e[0] for e in full] == list(range(1, len(full) + 1))


async def test_cancel_while_waiting_ends_the_stream(authed: AsyncClient) -> None:
    ws = await _ws(authed)
    run = await _start(authed, ws)
    base = f"/api/v1/workspaces/{ws}/agent/runs/{run['id']}"
    await execute_run(uuid.UUID(run["id"]), service=svc(_fake()))
    r = await authed.post(f"{base}/cancel")
    assert r.json()["status"] == "cancelled"
    events = _sse((await authed.get(f"{base}/stream")).text)
    assert events[-1][1] == "run_finished" and events[-1][2]["status"] == "cancelled"
    resume = await authed.post(
        f"{base}/resume", json={"decisions": [{"item_id": run["id"], "action": "approve"}]}
    )
    assert resume.status_code == 409


async def test_runs_are_private_to_the_workspace_owner(
    authed: AsyncClient, client: AsyncClient
) -> None:
    ws = await _ws(authed)
    run = await _start(authed, ws)
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "correct-horse-battery", "name": "O"},
    )
    headers = {"authorization": f"Bearer {other.json()['access_token']}"}
    r = await client.get(f"/api/v1/workspaces/{ws}/agent/runs/{run['id']}", headers=headers)
    assert r.status_code == 404
