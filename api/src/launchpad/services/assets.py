from __future__ import annotations

import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.domain.enums import AssetKind, AssetSource
from launchpad.models import Asset, BrandKit, Workspace
from launchpad.schemas.assets import AssetOut, LogoUploadOut, PaletteColorOut
from launchpad.services.colors import extract_palette
from launchpad.services.uploads import process_image, storage_key
from launchpad.storage import get_storage


async def asset_out(asset: Asset) -> AssetOut:
    url = await get_storage().signed_url(asset.storage_key)
    return AssetOut.model_validate({**_cols(asset), "url": url})


def _cols(asset: Asset) -> dict[str, object]:
    return {c: getattr(asset, c) for c in AssetOut.model_fields if c != "url"}


async def store_asset(
    db: AsyncSession,
    ws: Workspace,
    *,
    data: bytes,
    mime: str,
    kind: AssetKind,
    source: AssetSource,
    ext: str,
    width: int | None = None,
    height: int | None = None,
    parent_id: uuid.UUID | None = None,
    variant: str | None = None,
    meta: dict[str, object] | None = None,
    prompt: str | None = None,
) -> Asset:
    key = storage_key(ws.id, kind.value, ext)
    await get_storage().put(key, data, mime)
    asset = Asset(
        workspace_id=ws.id,
        kind=kind,
        source=source,
        storage_key=key,
        mime_type=mime,
        width=width,
        height=height,
        size_bytes=len(data),
        parent_id=parent_id,
        variant=variant,
        meta=meta or {},
        prompt=prompt,
    )
    db.add(asset)
    await db.flush()
    return asset


_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


async def upload_logo(db: AsyncSession, ws: Workspace, data: bytes, filename: str) -> LogoUploadOut:
    img = process_image(data)
    original = await store_asset(
        db, ws, data=img.original, mime=img.original_mime, kind=AssetKind.LOGO,
        source=AssetSource.UPLOADED, ext=_EXT[img.original_mime], width=img.width,
        height=img.height, variant="original", meta={"filename": filename[:200]},
    )  # fmt: skip
    normalized = await store_asset(
        db, ws, data=img.normalized_png, mime="image/png", kind=AssetKind.LOGO,
        source=AssetSource.UPLOADED, ext=".png", parent_id=original.id, variant="normalized",
        width=img.normalized_size[0], height=img.normalized_size[1],
    )  # fmt: skip
    thumb = await store_asset(
        db, ws, data=img.thumbnail_png, mime="image/png", kind=AssetKind.LOGO,
        source=AssetSource.UPLOADED, ext=".png", parent_id=original.id, variant="thumbnail",
        width=img.thumbnail_size[0], height=img.thumbnail_size[1],
    )  # fmt: skip
    palette = [PaletteColorOut.model_validate(asdict(c)) for c in extract_palette(img.image)]

    kit = await db.scalar(select(BrandKit).where(BrandKit.workspace_id == ws.id))
    assert kit is not None
    has_colors = bool(kit.primary_color or kit.secondary_color or kit.accent_colors)
    # The logo is attached; colours are only *suggested*. Applying them is a separate,
    # explicit brand-kit save, so a user's chosen colours are never overwritten silently.
    kit.logo_asset_id = normalized.id
    kit.logo_palette = [p.model_dump() for p in palette]
    await db.commit()
    return LogoUploadOut(
        logo=await asset_out(normalized),
        thumbnail=await asset_out(thumb),
        palette=palette,
        has_existing_colors=has_colors,
    )
