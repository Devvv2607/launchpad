"""Durable job execution.

`ScheduledJob` rows are the source of truth. Every minute the cron sweep claims due rows
with FOR UPDATE SKIP LOCKED (safe with several worker replicas), marks them RUNNING and
dispatches to a handler by kind. Failures retry with exponential backoff until
`max_attempts`, then the job is FAILED with the error recorded — never dropped silently.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import JobKind, JobStatus
from launchpad.models import ScheduledJob

log = structlog.get_logger("launchpad.worker")

Handler = Callable[[AsyncSession, ScheduledJob], Awaitable[None]]
HANDLERS: dict[JobKind, Handler] = {}

# A RUNNING job whose lock is older than this is assumed orphaned (worker crashed).
STALE_LOCK = timedelta(minutes=10)
CLAIM_BATCH = 20


class PermanentJobError(Exception):
    """Raise from a handler when retrying cannot help (e.g. item no longer approved)."""


def register(kind: JobKind) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


def backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(30 * 2 ** (attempt - 1), 3600))


async def claim_due(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(ScheduledJob)
        .where(
            or_(
                (ScheduledJob.status == JobStatus.PENDING) & (ScheduledJob.run_at <= now),
                (ScheduledJob.status == JobStatus.RUNNING)
                & (ScheduledJob.locked_at < now - STALE_LOCK),
            )
        )
        .order_by(ScheduledJob.run_at)
        .limit(CLAIM_BATCH)
        .with_for_update(skip_locked=True)
    )
    claimed = []
    for job in rows:
        job.status = JobStatus.RUNNING
        job.locked_at = now
        job.attempts += 1
        claimed.append(job.id)
    await session.commit()
    return claimed


async def execute(job_id: uuid.UUID) -> JobStatus:
    async with get_sessionmaker()() as session:
        job = await session.get(ScheduledJob, job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return JobStatus.CANCELLED
        bound = log.bind(job_id=str(job.id), kind=job.kind, attempt=job.attempts)
        handler = HANDLERS.get(job.kind)
        try:
            if handler is None:
                raise PermanentJobError(f"No handler registered for job kind '{job.kind}'")
            await handler(session, job)
        except PermanentJobError as exc:
            await session.rollback()
            job = await _reload(session, job_id)
            job.status, job.last_error = JobStatus.FAILED, str(exc)
            bound.error("job_failed_permanently", error=str(exc))
        except Exception as exc:
            await session.rollback()
            job = await _reload(session, job_id)
            job.last_error = f"{type(exc).__name__}: {exc}"
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.FAILED
                bound.error("job_failed", error=job.last_error)
            else:
                job.status = JobStatus.PENDING
                job.run_at = datetime.now(UTC) + backoff(job.attempts)
                bound.warning("job_retry_scheduled", error=job.last_error, run_at=job.run_at)
        else:
            job.status, job.last_error = JobStatus.SUCCEEDED, None
            bound.info("job_succeeded")
        job.locked_at = None
        await session.commit()
        return job.status


async def _reload(session: AsyncSession, job_id: uuid.UUID) -> ScheduledJob:
    job = await session.get(ScheduledJob, job_id, populate_existing=True)
    assert job is not None
    return job


async def sweep(ctx: dict[str, Any] | None = None) -> int:
    """Cron entrypoint: claim due jobs and run them. Returns the number processed."""
    async with get_sessionmaker()() as session:
        ids = await claim_due(session, datetime.now(UTC))
    for job_id in ids:
        await execute(job_id)
    if ids:
        log.info("sweep_processed", count=len(ids))
    return len(ids)
