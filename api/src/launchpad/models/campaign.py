from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from launchpad.db.base import Base, Timestamps, UUIDPk
from launchpad.domain.enums import CampaignGoal, CampaignStatus
from launchpad.models._types import JSON, str_enum


class Campaign(UUIDPk, Timestamps, Base):
    __tablename__ = "campaigns"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    goal: Mapped[CampaignGoal] = mapped_column(str_enum(CampaignGoal))
    brief: Mapped[str | None] = mapped_column(Text)
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    budget_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CampaignStatus] = mapped_column(
        str_enum(CampaignStatus), default=CampaignStatus.DRAFT
    )
    # Agent-produced calendar plan (validated by the plan_campaign schema), editable by users.
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
