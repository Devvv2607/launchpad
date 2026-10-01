from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from launchpad.db.base import Base, Timestamps, UUIDPk
from launchpad.domain.enums import AssetKind, AssetSource
from launchpad.models._types import JSON, str_enum


class Asset(UUIDPk, Timestamps, Base):
    """An image or poster (generated, rendered or uploaded) held in object storage."""

    __tablename__ = "assets"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AssetKind] = mapped_column(str_enum(AssetKind))
    source: Mapped[AssetSource] = mapped_column(str_enum(AssetSource))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # Poster renders in several sizes share a parent (the layout "master").
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    variant: Mapped[str | None] = mapped_column(String(32))  # e.g. "1080x1350", "a4"
    prompt: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
