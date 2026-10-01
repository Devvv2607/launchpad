from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from launchpad.db.base import Base, Timestamps, UUIDPk
from launchpad.domain.enums import Industry
from launchpad.models._types import JSON, str_enum
from launchpad.models.brand import BrandKit


class Workspace(UUIDPk, Timestamps, Base):
    """A business. Every other domain row hangs off a workspace."""

    __tablename__ = "workspaces"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    industry: Mapped[Industry] = mapped_column(str_enum(Industry))
    description: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[str | None] = mapped_column(Text)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    website: Mapped[str | None] = mapped_column(String(500))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")

    brand_kit: Mapped[BrandKit | None] = relationship(
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
