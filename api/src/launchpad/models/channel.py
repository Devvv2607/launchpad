from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from launchpad.db.base import Base, Timestamps, UUIDPk
from launchpad.domain.enums import ConnectionStatus, Platform
from launchpad.models._types import JSON, str_enum
from launchpad.security.crypto import EncryptedText


class ChannelConnection(UUIDPk, Timestamps, Base):
    """OAuth credentials for a publishing platform. Tokens are encrypted at rest."""

    __tablename__ = "channel_connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "platform", "account_id", name="uq_channel_account"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[Platform] = mapped_column(str_enum(Platform))
    account_id: Mapped[str] = mapped_column(String(255))
    account_name: Mapped[str | None] = mapped_column(String(255))
    access_token: Mapped[str | None] = mapped_column(EncryptedText)
    refresh_token: Mapped[str | None] = mapped_column(EncryptedText)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[ConnectionStatus] = mapped_column(
        str_enum(ConnectionStatus), default=ConnectionStatus.ACTIVE
    )
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text)


class MetricSnapshot(UUIDPk, Base):
    """Real metrics pulled from a platform insights API at `captured_at`."""

    __tablename__ = "metric_snapshots"
    __table_args__ = (
        Index("ix_metric_snapshots_item_time", "content_item_id", "captured_at"),
        Index("ix_metric_snapshots_ws_time", "workspace_id", "captured_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channel_connections.id", ondelete="SET NULL")
    )
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(str_enum(Platform))
    external_id: Mapped[str] = mapped_column(String(255))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # e.g. {"impressions": 1200, "reach": 900, "likes": 80, "comments": 6, "saves": 12}
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
