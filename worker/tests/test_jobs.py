from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import JobKind, JobStatus
from launchpad.models import ScheduledJob, User, Workspace
from launchpad_worker import jobs


@pytest.fixture
def handlers() -> Iterator[dict[JobKind, jobs.Handler]]:
    saved = dict(jobs.HANDLERS)
    jobs.HANDLERS.clear()
    yield jobs.HANDLERS
    jobs.HANDLERS.clear()
    jobs.HANDLERS.update(saved)


async def _job(run_at: datetime, **kw: object) -> uuid.UUID:
    async with get_sessionmaker()() as db:
        user = User(email=f"{uuid.uuid4().hex}@example.com")
        db.add(user)
        await db.flush()
        ws = Workspace(owner_id=user.id, name="W", industry="food")
        db.add(ws)
        await db.flush()
        job = ScheduledJob(workspace_id=ws.id, kind=JobKind.PUBLISH, run_at=run_at, **kw)
        db.add(job)
        await db.commit()
        return job.id


async def _get(job_id: uuid.UUID) -> ScheduledJob:
    async with get_sessionmaker()() as db:
        job = await db.get(ScheduledJob, job_id)
        assert job is not None
        return job


async def test_due_job_runs_and_future_job_waits(handlers: dict[JobKind, jobs.Handler]) -> None:
    ran: list[uuid.UUID] = []

    async def handle(_db: AsyncSession, job: ScheduledJob) -> None:
        ran.append(job.id)

    handlers[JobKind.PUBLISH] = handle
    now = datetime.now(UTC)
    due = await _job(now - timedelta(seconds=5))
    future = await _job(now + timedelta(hours=1))

    assert await jobs.sweep() == 1
    assert ran == [due]
    assert (await _get(due)).status == JobStatus.SUCCEEDED
    assert (await _get(future)).status == JobStatus.PENDING


async def test_failure_retries_with_backoff_then_fails(
    handlers: dict[JobKind, jobs.Handler],
) -> None:
    async def boom(_db: AsyncSession, _job: ScheduledJob) -> None:
        raise RuntimeError("platform 503")

    handlers[JobKind.PUBLISH] = boom
    job_id = await _job(datetime.now(UTC) - timedelta(seconds=1), max_attempts=2)

    await jobs.sweep()
    job = await _get(job_id)
    assert job.status == JobStatus.PENDING and job.attempts == 1
    assert job.last_error == "RuntimeError: platform 503"
    assert job.run_at > datetime.now(UTC)

    # Pretend the backoff elapsed.
    async with get_sessionmaker()() as db:
        j = await db.get(ScheduledJob, job_id)
        assert j is not None
        j.run_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    await jobs.sweep()
    job = await _get(job_id)
    assert job.status == JobStatus.FAILED and job.attempts == 2


async def test_unknown_kind_fails_loudly(handlers: dict[JobKind, jobs.Handler]) -> None:
    job_id = await _job(datetime.now(UTC) - timedelta(seconds=1))
    await jobs.sweep()
    job = await _get(job_id)
    assert job.status == JobStatus.FAILED
    assert job.last_error is not None and "No handler" in job.last_error


async def test_concurrent_sweeps_never_double_run(
    handlers: dict[JobKind, jobs.Handler],
) -> None:
    calls: list[uuid.UUID] = []

    async def slow(_db: AsyncSession, job: ScheduledJob) -> None:
        calls.append(job.id)
        await asyncio.sleep(0.05)

    handlers[JobKind.PUBLISH] = slow
    now = datetime.now(UTC) - timedelta(seconds=1)
    ids = [await _job(now) for _ in range(6)]

    await asyncio.gather(jobs.sweep(), jobs.sweep(), jobs.sweep())
    assert sorted(calls) == sorted(ids)
