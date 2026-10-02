from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from launchpad.domain.enums import Channel, ContentStatus
from launchpad.schemas.common import Schema

TEXT_CHANNELS = [
    Channel.INSTAGRAM_POST,
    Channel.INSTAGRAM_CAROUSEL,
    Channel.LINKEDIN_POST,
    Channel.X_POST,
    Channel.EMAIL,
]


class GenerateIn(Schema):
    channel: Channel
    brief: str = Field(min_length=5, max_length=2000)
    n_variants: int = Field(default=3, ge=1, le=4)
    critique: bool = True
    campaign_id: uuid.UUID | None = None


class ViolationOut(Schema):
    rule: str
    severity: str
    message: str
    field: str = ""


class ContentItemOut(Schema):
    id: uuid.UUID
    channel: Channel
    title: str | None
    body: str
    payload: dict[str, Any]
    hashtags: list[str]
    variant_group: uuid.UUID | None
    variant_label: str | None
    status: ContentStatus
    critique_score: int | None
    generation: dict[str, Any]
    violations: list[ViolationOut] = Field(default_factory=list)
    blocked: bool = False  # has hard platform violations; can't be approved until fixed
    campaign_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ContentEditIn(Schema):
    """Inline edit: send the full structured content for the item's channel."""

    content: dict[str, Any]
    title: str | None = Field(default=None, max_length=200)


class HashtagsIn(Schema):
    channel: Channel
    text: str = Field(min_length=3, max_length=5000)


class HashtagsOut(Schema):
    broad: list[str]
    niche: list[str]
    branded: list[str]
    local: list[str]
