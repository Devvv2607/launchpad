from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from launchpad.api.deps import DB
from launchpad.domain.enums import Channel, Industry
from launchpad.schemas.common import Schema

router = APIRouter(tags=["meta"])


class HealthOut(Schema):
    status: str
    database: str


class MetaOut(Schema):
    industries: list[Industry]
    channels: list[Channel]


@router.get("/health", response_model=HealthOut)
async def health(db: DB) -> HealthOut:
    try:
        await db.execute(text("select 1"))
        database = "ok"
    except Exception as exc:
        database = f"error: {type(exc).__name__}"
    return HealthOut(status="ok" if database == "ok" else "degraded", database=database)


@router.get("/meta", response_model=MetaOut)
async def meta() -> MetaOut:
    return MetaOut(industries=list(Industry), channels=list(Channel))
