from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from launchpad.api.deps import DB, CurrentUser, CurrentWorkspace
from launchpad.models import BrandKit, Workspace
from launchpad.schemas.workspace import (
    BrandKitIn,
    BrandKitOut,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(user: CurrentUser, db: DB) -> list[Workspace]:
    rows = await db.scalars(
        select(Workspace).where(Workspace.owner_id == user.id).order_by(Workspace.created_at)
    )
    return list(rows)


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(body: WorkspaceCreate, user: CurrentUser, db: DB) -> Workspace:
    data = body.model_dump(mode="json")
    ws = Workspace(owner_id=user.id, **data)
    ws.brand_kit = BrandKit()
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(ws: CurrentWorkspace) -> Workspace:
    return ws


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(body: WorkspaceUpdate, ws: CurrentWorkspace, db: DB) -> Workspace:
    for field, value in body.model_dump(mode="json", exclude_unset=True).items():
        setattr(ws, field, value)
    await db.commit()
    await db.refresh(ws)
    return ws


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(ws: CurrentWorkspace, db: DB) -> None:
    await db.delete(ws)
    await db.commit()


@router.get("/{workspace_id}/brand-kit", response_model=BrandKitOut)
async def get_brand_kit(ws: CurrentWorkspace, db: DB) -> BrandKit:
    return await _brand_kit(ws, db)


@router.put("/{workspace_id}/brand-kit", response_model=BrandKitOut)
async def put_brand_kit(body: BrandKitIn, ws: CurrentWorkspace, db: DB) -> BrandKit:
    kit = await _brand_kit(ws, db)
    for field, value in body.model_dump().items():
        setattr(kit, field, value)
    await db.commit()
    await db.refresh(kit)
    return kit


async def _brand_kit(ws: Workspace, db: DB) -> BrandKit:
    kit = await db.scalar(select(BrandKit).where(BrandKit.workspace_id == ws.id))
    if kit is None:  # Defensive: every workspace is created with one.
        kit = BrandKit(workspace_id=ws.id)
        db.add(kit)
        await db.commit()
        await db.refresh(kit)
    return kit
