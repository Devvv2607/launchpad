from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from launchpad.db.base import Base, Timestamps, UUIDPk
from launchpad.domain.enums import JobKind, JobStatus
from launchpad.models._types import JSON, str_enum


class ScheduledJob(UUIDPk, Timestamps, Base):
    """Durable job record. The DB is the source of truth; Redis/ARQ is only the transport.

    The worker's cron sweep claims due rows with SELECT ... FOR UPDATE SKIP LOCKED, so jobs
    survive Redis restarts and can never be double-published.
    """

    __tablename__ = "scheduled_jobs"
    __table_args__ = (Index("ix_scheduled_jobs_due", "status", "run_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[JobKind] = mapped_column(str_enum(JobKind))
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), index=True
    )
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), default=JobStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    dry_run: Mapped[bool] = mapped_column(default=False)
    publisher: Mapped[str | None] = mapped_column(String(32))
