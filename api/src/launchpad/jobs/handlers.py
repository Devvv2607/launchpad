"""Job handlers executed by the worker. Kept in the shared package so they can be tested
without the worker process; the worker registers them at startup."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.domain.enums import DocumentStatus, JobKind
from launchpad.jobs import PermanentJobError
from launchpad.llm.errors import LLMError
from launchpad.llm.service import CallContext
from launchpad.models import BrandDocument, ScheduledJob, Workspace
from launchpad.rag.crawl import CrawlError
from launchpad.rag.extract import ExtractionError
from launchpad.rag.service import ingest

log = structlog.get_logger(__name__)


async def ingest_document(db: AsyncSession, job: ScheduledJob) -> None:
    doc_id = uuid.UUID(str(job.payload["document_id"]))
    doc = await db.get(BrandDocument, doc_id)
    if doc is None:
        raise PermanentJobError("Document was deleted before it could be processed.")
    ws = await db.get(Workspace, doc.workspace_id)
    assert ws is not None
    user_id = job.payload.get("user_id")
    ctx = CallContext.for_workspace(ws, uuid.UUID(user_id) if user_id else None)

    doc.status = DocumentStatus.PROCESSING
    await db.commit()
    try:
        await ingest(db, doc, ctx)
    except (ExtractionError, CrawlError) as exc:
        await _fail(db, doc, str(exc))
        raise PermanentJobError(str(exc)) from exc
    except LLMError as exc:
        message = exc.message + (f" {exc.hint}" if exc.hint else "")
        if exc.retryable and job.attempts < job.max_attempts:
            await _fail(db, doc, f"Temporary problem, retrying: {message}", DocumentStatus.PENDING)
            raise  # transient: the worker retries with backoff
        await _fail(db, doc, message)
        raise PermanentJobError(message) from exc


async def _fail(
    db: AsyncSession,
    doc: BrandDocument,
    reason: str,
    status: DocumentStatus = DocumentStatus.FAILED,
) -> None:
    await db.rollback()
    fresh = await db.get(BrandDocument, doc.id, populate_existing=True)
    if fresh is not None:
        fresh.status = status
        fresh.error = reason[:1000]
        await db.commit()


async def agent_run(db: AsyncSession, job: ScheduledJob) -> None:
    from launchpad.agent.runner import execute_run

    run_id = uuid.UUID(str(job.payload["run_id"]))
    decisions = job.payload.get("decisions")
    await execute_run(run_id, decisions=decisions)


HANDLERS = {JobKind.INGEST_DOCUMENT: ingest_document, JobKind.AGENT_RUN: agent_run}
