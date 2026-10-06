from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from launchpad.domain.enums import AgentRunStatus
from launchpad.schemas.common import Schema


class RunCreateIn(Schema):
    message: str = Field(min_length=2, max_length=4000)
    # Continue an existing conversation; omit to start a new thread.
    thread_id: str | None = Field(default=None, max_length=64)
    campaign_id: uuid.UUID | None = None


class DecisionIn(Schema):
    item_id: uuid.UUID
    action: Literal["approve", "reject", "edit"]
    # For "edit": the full structured content for the item's channel.
    content: dict[str, Any] | None = None


class ResumeIn(Schema):
    decisions: list[DecisionIn] = Field(min_length=1, max_length=50)


class RunOut(Schema):
    id: uuid.UUID
    thread_id: str
    title: str | None
    status: AgentRunStatus
    input: str | None
    final: str | None
    error: str | None
    tool_calls: int
    tokens_in: int
    cost_usd: Decimal
    token_budget: int
    cost_budget_usd: Decimal
    created_at: datetime
    finished_at: datetime | None


class EventOut(Schema):
    seq: int
    type: str
    data: dict[str, Any]
    created_at: datetime


class RunDetailOut(RunOut):
    events: list[EventOut]
