from __future__ import annotations

import mimetypes
import uuid

from fastapi import APIRouter, File, Query, Response, UploadFile, status
from sqlalchemy import select

from launchpad.api.deps import DB, CurrentWorkspace
from launchpad.api.errors import Forbidden, NotFound
from launchpad.domain.enums import AssetKind
from launchpad.models import Asset
from launchpad.schemas.assets import AssetOut, LogoUploadOut
from launchpad.services.assets import asset_out, upload_logo
from launchpad.services.uploads import MAX_IMAGE_BYTES
from launchpad.storage import LocalStorage, ObjectNotFound, get_storage, verify_local_signature

router = APIRouter(tags=["assets"])


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    return data  # size checked (with a clear message) by the processing step


@router.post("/workspaces/{workspace_id}/brand-kit/logo", response_model=LogoUploadOut)
async def upload_brand_logo(
    ws: CurrentWorkspace, db: DB, file: UploadFile = File(...)
) -> LogoUploadOut:
    data = await _read_limited(file, MAX_IMAGE_BYTES)
    return await upload_logo(db, ws, data, file.filename or "logo")


@router.get("/workspaces/{workspace_id}/assets", response_model=list[AssetOut])
async def list_assets(
    ws: CurrentWorkspace,
    db: DB,
    kind: AssetKind | None = None,
    include_variants: bool = False,
    limit: int = Query(default=100, le=500),
) -> list[AssetOut]:
    q = select(Asset).where(Asset.workspace_id == ws.id)
    if kind:
        q = q.where(Asset.kind == kind)
    if not include_variants:
        q = q.where(Asset.parent_id.is_(None))
    rows = await db.scalars(q.order_by(Asset.created_at.desc()).limit(limit))
    return [await asset_out(a) for a in rows]


@router.delete(
    "/workspaces/{workspace_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_asset(asset_id: uuid.UUID, ws: CurrentWorkspace, db: DB) -> None:
    asset = await db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != ws.id:
        raise NotFound("Asset not found.")
    children = list(await db.scalars(select(Asset).where(Asset.parent_id == asset.id)))
    for a in [*children, asset]:
        await get_storage().delete(a.storage_key)
    await db.delete(asset)  # children cascade in the DB
    await db.commit()


@router.get("/files/{key:path}", include_in_schema=False)
async def serve_local_file(key: str, exp: int, sig: str) -> Response:
    """Serves local-storage objects behind expiring HMAC signatures (S3 uses presigned URLs)."""
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise NotFound("Not found.")
    if not verify_local_signature(key, exp, sig):
        raise Forbidden("This link is invalid or has expired.")
    try:
        data = await storage.get(key)
    except ObjectNotFound as exc:
        raise NotFound("File not found.") from exc
    media_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(
        data,
        media_type=media_type,
        headers={"cache-control": "private, max-age=3600", "x-content-type-options": "nosniff"},
    )
