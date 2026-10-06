from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from launchpad.db.base import Base, UUIDPk
from launchpad.models._types import JSON


class IdempotencyKey(UUIDPk, Base):
    """One client action (an `Idempotency-Key` header) per workspace and endpoint scope.

    The first request claims the key and does the work; a repeat with the same key gets the
    first request's result instead of doing the work again.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        Index("ix_idempotency_scope_key", "workspace_id", "scope", "key", unique=True),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(32))  # e.g. "content.generate", "agent.run"
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="in_progress")  # in_progress | done
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
