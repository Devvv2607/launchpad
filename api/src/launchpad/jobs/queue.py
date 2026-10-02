"""Create durable jobs. The ScheduledJob row is the source of truth; the Redis enqueue is
only a fast path. If Redis is unavailable the worker's cron sweep picks the job up within
~30s, and the delay is logged (not hidden)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.config import get_settings
from launchpad.domain.enums import JobKind
from launchpad.models import ScheduledJob

log = structlog.get_logger(__name__)


async def enqueue(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    kind: JobKind,
    payload: dict[str, Any],
    run_at: datetime | None = None,
    content_item_id: uuid.UUID | None = None,
    max_attempts: int = 3,
) -> ScheduledJob:
    job = ScheduledJob(
        workspace_id=workspace_id,
        kind=kind,
        payload=payload,
        run_at=run_at or datetime.now(UTC),
        content_item_id=content_item_id,
        max_attempts=max_attempts,
    )
    db.add(job)
    await db.commit()
    if job.run_at <= datetime.now(UTC):
        await _poke_worker(job.id)
    return job


async def _poke_worker(job_id: uuid.UUID) -> None:
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            await pool.enqueue_job("run_job_now", str(job_id))
        finally:
            await pool.aclose()
    except Exception as exc:  # Redis down etc. — the cron sweep still runs the job
        log.warning(
            "worker_poke_failed_job_will_run_on_next_sweep", job_id=str(job_id), error=str(exc)
        )
