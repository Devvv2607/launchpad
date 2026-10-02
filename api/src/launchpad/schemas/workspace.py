from __future__ import annotations

import re
import uuid
from datetime import datetime
from zoneinfo import available_timezones

from pydantic import Field, HttpUrl, field_validator

from launchpad.domain.enums import Industry
from launchpad.schemas.assets import PaletteColorOut
from launchpad.schemas.brand import VoiceProfile
from launchpad.schemas.common import Schema

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class WorkspaceBase(Schema):
    name: str = Field(min_length=1, max_length=120)
    industry: Industry
    description: str | None = Field(default=None, max_length=2000)
    audience: str | None = Field(default=None, max_length=2000)
    locations: list[str] = Field(default_factory=list, max_length=20)
    website: HttpUrl | None = None
    timezone: str = "Asia/Kolkata"

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        if v not in available_timezones():
            raise ValueError(f"Unknown timezone: {v}")
        return v


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    industry: Industry | None = None
    description: str | None = Field(default=None, max_length=2000)
    audience: str | None = Field(default=None, max_length=2000)
    locations: list[str] | None = Field(default=None, max_length=20)
    website: HttpUrl | None = None
    timezone: str | None = None


class WorkspaceOut(Schema):
    id: uuid.UUID
    name: str
    industry: Industry
    description: str | None
    audience: str | None
    locations: list[str]
    website: str | None
    timezone: str
    created_at: datetime
    updated_at: datetime


def _check_hex(v: str | None) -> str | None:
    if v is not None and not _HEX.match(v):
        raise ValueError("Colour must be a hex value like #1A2B3C")
    return v.upper() if v else v


class BrandKitIn(Schema):
    logo_asset_id: uuid.UUID | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    accent_colors: list[str] = Field(default_factory=list, max_length=6)
    heading_font: str | None = Field(default=None, max_length=80)
    body_font: str | None = Field(default=None, max_length=80)
    voice_tone: str | None = Field(default=None, max_length=4000)
    do_words: list[str] = Field(default_factory=list, max_length=50)
    dont_words: list[str] = Field(default_factory=list, max_length=50)
    sample_posts: list[str] = Field(default_factory=list, max_length=10)
    voice_profile: VoiceProfile | None = None

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def _colors(cls, v: str | None) -> str | None:
        return _check_hex(v)

    @field_validator("accent_colors")
    @classmethod
    def _accents(cls, v: list[str]) -> list[str]:
        return [c for c in (_check_hex(x) for x in v) if c]


class BrandKitOut(BrandKitIn):
    id: uuid.UUID
    workspace_id: uuid.UUID
    updated_at: datetime
    logo_url: str | None = None
    logo_palette: list[PaletteColorOut] = Field(default_factory=list)
    voice_profile: VoiceProfile | None = None
