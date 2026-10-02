from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from launchpad.domain.enums import AssetKind, AssetSource
from launchpad.schemas.common import Schema


class AssetOut(Schema):
    id: uuid.UUID
    kind: AssetKind
    source: AssetSource
    mime_type: str
    width: int | None
    height: int | None
    size_bytes: int | None
    variant: str | None
    parent_id: uuid.UUID | None
    meta: dict[str, Any]
    created_at: datetime
    url: str  # short-lived signed URL


class PaletteColorOut(Schema):
    hex: str
    share: float
    role: Literal["primary", "secondary", "accent", "extra"]
    contrast_white: float
    contrast_black: float
    rating_on_white: Literal["AAA", "AA", "AA large", "fail"]
    rating_on_black: Literal["AAA", "AA", "AA large", "fail"]
    best_text: Literal["#FFFFFF", "#000000"]


class LogoUploadOut(Schema):
    logo: AssetOut
    thumbnail: AssetOut
    palette: list[PaletteColorOut]
    # True when the kit already has colours: the UI must ask before replacing them.
    has_existing_colors: bool
