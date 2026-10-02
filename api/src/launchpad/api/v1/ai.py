"""Settings → AI: per-purpose routing, spend cap, and real usage from llm_calls."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import case, func, select

from launchpad.api.deps import DB, CurrentWorkspace
from launchpad.api.errors import AppError
from launchpad.config import get_settings
from launchpad.llm.capabilities import caps_for
from launchpad.llm.errors import LLMNotConfiguredError
from launchpad.llm.pricing import PRICES
from launchpad.llm.registry import AISettings, PurposeRoute, configured_providers, resolve
from launchpad.llm.service import CallContext, daily_cap, spent_today
from launchpad.llm.types import Purpose
from launchpad.models import LLMCall
from launchpad.schemas.common import Schema

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["ai"])


class CatalogModel(Schema):
    provider: str
    model: str
    input_per_m: float | None
    output_per_m: float | None
    price_official: bool | None
    structured: str
    embedding: bool


class EffectiveRoute(Schema):
    provider: str | None
    model: str | None
    source: str  # workspace | env | unconfigured
    error: str | None = None


class AISettingsOut(Schema):
    routes: dict[Purpose, PurposeRoute]
    daily_spend_cap_usd: float | None
    default_daily_cap_usd: float
    effective: dict[Purpose, EffectiveRoute]
    configured_providers: list[str]
    catalog: list[CatalogModel]


class AISettingsIn(Schema):
    routes: dict[Purpose, PurposeRoute] = Field(default_factory=dict)
    daily_spend_cap_usd: float | None = Field(default=None, ge=0, le=1000)


def _catalog() -> list[CatalogModel]:
    providers = set(configured_providers())
    out = []
    for (provider, model), price in sorted(PRICES.items()):
        if provider not in providers:
            continue
        out.append(
            CatalogModel(
                provider=provider, model=model,
                input_per_m=float(price.input_per_m), output_per_m=float(price.output_per_m),
                price_official=price.official, structured=caps_for(provider, model).structured,
                embedding="embedding" in model,
            )
        )  # fmt: skip
    return out


def _effective(ai: AISettings) -> dict[Purpose, EffectiveRoute]:
    out: dict[Purpose, EffectiveRoute] = {}
    for p in Purpose:
        try:
            r = resolve(p, ai)
            out[p] = EffectiveRoute(provider=r.provider, model=r.model, source=r.source)
        except LLMNotConfiguredError as exc:
            out[p] = EffectiveRoute(
                provider=None, model=None, source="unconfigured", error=exc.hint or exc.message
            )
    return out


def _out(ai: AISettings) -> AISettingsOut:
    return AISettingsOut(
        routes=ai.routes,
        daily_spend_cap_usd=ai.daily_spend_cap_usd,
        default_daily_cap_usd=get_settings().daily_spend_cap_usd,
        effective=_effective(ai),
        configured_providers=configured_providers(),
        catalog=_catalog(),
    )


@router.get("/ai-settings", response_model=AISettingsOut)
async def get_ai_settings(ws: CurrentWorkspace) -> AISettingsOut:
    return _out(AISettings.model_validate(ws.ai_settings or {}))


@router.put("/ai-settings", response_model=AISettingsOut)
async def put_ai_settings(body: AISettingsIn, ws: CurrentWorkspace, db: DB) -> AISettingsOut:
    available = set(configured_providers())
    for purpose, route in body.routes.items():
        if route.provider not in available:
            raise AppError(
                f"'{purpose}' can't use {route.provider}: no API key is configured for it."
            )
        if purpose == Purpose.EMBEDDING and route.provider not in ("gemini", "openai"):
            raise AppError(f"{route.provider} doesn't provide embeddings.")
    ai = AISettings(routes=body.routes, daily_spend_cap_usd=body.daily_spend_cap_usd)
    ws.ai_settings = ai.model_dump(mode="json")
    await db.commit()
    return _out(ai)


class UsageRow(Schema):
    key: str
    calls: int
    errors: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    unknown_cost_calls: int


class UsageOut(Schema):
    month: str
    timezone: str
    totals: UsageRow
    by_task: list[UsageRow]
    by_model: list[UsageRow]
    by_day: list[UsageRow]
    today_spent_usd: float
    daily_cap_usd: float


def _month_bounds(month: str | None, tz: str) -> tuple[str, datetime, datetime]:
    zone = ZoneInfo(tz)
    today = datetime.now(zone).date()
    if month:
        try:
            year, mon = (int(x) for x in month.split("-"))
            start = date(year, mon, 1)
        except ValueError as exc:
            raise AppError("month must look like 2026-10") from exc
    else:
        start = today.replace(day=1)
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)

    def as_utc(d: date) -> datetime:
        return datetime.combine(d, time.min, zone).astimezone(UTC)

    return start.strftime("%Y-%m"), as_utc(start), as_utc(end)


@router.get("/usage", response_model=UsageOut)
async def usage(ws: CurrentWorkspace, db: DB, month: str | None = Query(default=None)) -> UsageOut:
    label, start, end = _month_bounds(month, ws.timezone)
    base = (
        (LLMCall.workspace_id == ws.id) & (LLMCall.created_at >= start) & (LLMCall.created_at < end)
    )
    cols = (
        func.count(),
        func.sum(case((LLMCall.status == "error", 1), else_=0)),
        func.coalesce(func.sum(LLMCall.tokens_in), 0),
        func.coalesce(func.sum(LLMCall.tokens_out), 0),
        func.coalesce(func.sum(LLMCall.cost_usd), 0),
        func.sum(case((LLMCall.cost_usd.is_(None) & (LLMCall.status == "ok"), 1), else_=0)),
    )

    def row(key: str, r: tuple[Any, ...]) -> UsageRow:
        calls, errors, tin, tout, cost, unknown = r
        return UsageRow(
            key=key, calls=int(calls or 0), errors=int(errors or 0),
            tokens_in=int(tin or 0), tokens_out=int(tout or 0),
            cost_usd=float(Decimal(str(cost or 0))), unknown_cost_calls=int(unknown or 0),
        )  # fmt: skip

    totals = (await db.execute(select(*cols).where(base))).one()
    by_task = (
        await db.execute(select(LLMCall.purpose, *cols).where(base).group_by(LLMCall.purpose))
    ).all()
    model_key = LLMCall.provider + ":" + LLMCall.model
    by_model = (await db.execute(select(model_key, *cols).where(base).group_by(model_key))).all()
    day_key = func.to_char(func.timezone(ws.timezone, LLMCall.created_at), "YYYY-MM-DD")
    by_day = (
        await db.execute(select(day_key, *cols).where(base).group_by(day_key).order_by(day_key))
    ).all()

    ctx = CallContext.for_workspace(ws, None)
    return UsageOut(
        month=label,
        timezone=ws.timezone,
        totals=row("total", tuple(totals)),
        by_task=sorted((row(str(r[0]), tuple(r[1:])) for r in by_task), key=lambda u: -u.cost_usd),
        by_model=sorted(
            (row(str(r[0]), tuple(r[1:])) for r in by_model), key=lambda u: -u.cost_usd
        ),
        by_day=[row(str(r[0]), tuple(r[1:])) for r in by_day],
        today_spent_usd=float(await spent_today(ws.id, ws.timezone)),
        daily_cap_usd=float(daily_cap(ctx)),
    )
