from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from launchpad.db.base import Base, Timestamps, UUIDPk
from launchpad.domain.enums import Channel, ContentStatus
from launchpad.models._types import JSON, str_enum


class ContentItem(UUIDPk, Timestamps, Base):
    __tablename__ = "content_items"
    __table_args__ = (
        Index("ix_content_items_ws_status", "workspace_id", "status"),
        Index("ix_content_items_ws_scheduled", "workspace_id", "scheduled_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
    channel: Mapped[Channel] = mapped_column(str_enum(Channel))
    title: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    # Channel-specific structured fields: email subject/preheader/html, carousel slides, etc.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list)
    variant_group: Mapped[uuid.UUID | None] = mapped_column(index=True)
    variant_label: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_id: Mapped[str | None] = mapped_column(String(255))
    external_url: Mapped[str | None] = mapped_column(String(1000))
    error: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    critique_score: Mapped[int | None] = mapped_column(Integer)


class ContentAsset(Base):
    """Ordered media attached to a content item (carousel slides, hero image, poster)."""

    __tablename__ = "content_assets"

    content_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
