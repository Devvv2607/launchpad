"""ARQ worker entrypoint: `arq launchpad_worker.main.WorkerSettings`."""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from typing import Any

import structlog
from arq import cron
from arq.connections import RedisSettings

from launchpad.config import get_settings
from launchpad.db.session import get_engine
from launchpad.jobs.handlers import HANDLERS as SHARED_HANDLERS
from launchpad.logging import configure_logging
from launchpad_worker.jobs import HANDLERS, execute, sweep

HANDLERS.update(SHARED_HANDLERS)

if sys.platform == "win32":
    # psycopg (LangGraph's Postgres checkpointer) can't run on the default Proactor loop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

log = structlog.get_logger("launchpad.worker")


async def startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    logging.getLogger("arq").propagate = False  # arq has its own handler; avoid duplicates
    log.info("worker_started", handlers=sorted(HANDLERS))


async def shutdown(ctx: dict[str, Any]) -> None:
    await get_engine().dispose()


async def run_job_now(ctx: dict[str, Any], job_id: str) -> None:
    """Fast path: the API can enqueue a sweep immediately instead of waiting for cron."""
    await sweep(ctx)


async def execute_job(ctx: dict[str, Any], job_id: str) -> None:
    """Runs one claimed ScheduledJob (dispatched by the sweep)."""
    await execute(uuid.UUID(job_id))


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions = [run_job_now, execute_job]
    cron_jobs = [cron(sweep, second={0, 30}, run_at_startup=True, unique=True)]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 1800  # agent runs; the DB heartbeat keeps the claim alive meanwhile
