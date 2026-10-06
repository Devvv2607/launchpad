"""The one entry point features use to call an LLM.

    result, call_id = await llm.generate(ctx, Purpose.WRITING, prompt, schema=Drafts)

Per call it: resolves provider/model (workspace override → env default), enforces the
workspace's daily spend cap, calls the provider, and writes an `llm_calls` row — on success
*and* on failure — in its own transaction, so usage is recorded even if the caller rolls back.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from launchpad.config import get_settings
from launchpad.db.session import get_sessionmaker
from launchpad.llm.base import LLMClient
from launchpad.llm.errors import LLMBadRequestError, LLMError, SpendCapExceededError
from launchpad.llm.registry import AISettings, Route, get_client, resolve
from launchpad.llm.types import (
    LLMResult,
    Message,
    Purpose,
    Reasoning,
    StreamDone,
    StreamEvent,
    ToolSpec,
    Usage,
)
from launchpad.models import LLMCall, Workspace
from launchpad.prompts import RenderedPrompt

log = structlog.get_logger("launchpad.llm")
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class CallContext:
    """Who/what a call is for. Built once per request or agent run."""

    workspace_id: uuid.UUID
    user_id: uuid.UUID | None
    timezone: str = "Asia/Kolkata"
    ai: AISettings | None = None
    run_id: uuid.UUID | None = None

    @classmethod
    def for_workspace(
        cls, ws: Workspace, user_id: uuid.UUID | None, run_id: uuid.UUID | None = None
    ) -> CallContext:
        try:
            ai = AISettings.model_validate(ws.ai_settings or {})
        except ValidationError:
            log.warning("invalid_ai_settings_ignored", workspace_id=str(ws.id))
            ai = None
        return cls(ws.id, user_id, ws.timezone, ai, run_id)


def _day_start_utc(tz: str) -> datetime:
    zone = ZoneInfo(tz)
    local_midnight = datetime.combine(datetime.now(zone).date(), time.min, zone)
    return local_midnight.astimezone(UTC)


async def spent_today(workspace_id: uuid.UUID, tz: str) -> Decimal:
    async with get_sessionmaker()() as db:
        total = await db.scalar(
            select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(
                LLMCall.workspace_id == workspace_id,
                LLMCall.created_at >= _day_start_utc(tz),
            )
        )
    return Decimal(total or 0)


def daily_cap(ctx: CallContext) -> Decimal:
    if ctx.ai and ctx.ai.daily_spend_cap_usd is not None:
        return Decimal(str(ctx.ai.daily_spend_cap_usd))
    return Decimal(str(get_settings().daily_spend_cap_usd))


async def check_spend_cap(ctx: CallContext) -> None:
    cap = daily_cap(ctx)
    spent = await spent_today(ctx.workspace_id, ctx.timezone)
    if spent >= cap:
        raise SpendCapExceededError(
            f"Today's AI spend cap of ${cap:.2f} is reached (spent ${spent:.4f}).",
            hint="Raise the daily cap in Settings → AI, or try again tomorrow.",
            details={"cap_usd": str(cap), "spent_usd": str(spent)},
        )


def _messages(prompt: RenderedPrompt | None, messages: list[Message] | None) -> list[Message]:
    if messages is not None:
        return messages
    if prompt is None:
        raise ValueError("Pass a rendered prompt or explicit messages.")
    return [Message("system", prompt.system), Message("user", prompt.user)]


async def _record(
    *,
    ctx: CallContext,
    route: Route,
    purpose: Purpose,
    task: str,
    prompt: RenderedPrompt | None,
    result: LLMResult[Any] | None,
    error: LLMError | None,
    messages: list[Message],
    usage_on_error: Usage | None = None,
) -> uuid.UUID:
    s = get_settings()
    payload = None
    if s.log_llm_payloads:
        payload = {
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "output": result.text if result else None,
        }
    usage = result.usage if result else (usage_on_error or Usage())
    row = LLMCall(
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        run_id=ctx.run_id,
        provider=route.provider,
        model=route.model,
        purpose=task,
        route=purpose.value,
        status="ok" if error is None else "error",
        error_code=error.code if error else None,
        error=error.message[:2000] if error else None,
        prompt_name=prompt.name if prompt else None,
        prompt_version=prompt.version if prompt else None,
        request_id=(result.request_id if result else (error.request_id if error else None)),
        attempts=result.attempts if result else 1,
        tokens_in=usage.input_tokens,
        tokens_out=usage.output_tokens,
        cost_usd=result.cost_usd if result else None,
        latency_ms=result.latency_ms if result else 0,
        payload=payload,
    )
    async with get_sessionmaker()() as db:
        db.add(row)
        await db.commit()
    log.info(
        "llm_call",
        task=task,
        provider=route.provider,
        model=route.model,
        status=row.status,
        error_code=row.error_code,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        cost_usd=str(row.cost_usd) if row.cost_usd is not None else "unknown",
        latency_ms=row.latency_ms,
        prompt_version=row.prompt_version,
    )
    return row.id


MIN_OUTPUT_TOKENS = 1024


def estimate_input_tokens(
    msgs: list[Message], tools: list[ToolSpec] | None, schema: type[BaseModel] | None
) -> int:
    """Deliberately generous (3 chars per token) so a clamped request still fits."""
    chars = sum(len(m.content) + 16 for m in msgs)
    chars += sum(len(json.dumps(t.parameters)) + len(t.description) for t in tools or [])
    if schema is not None:
        chars += len(json.dumps(schema.model_json_schema()))
    return chars // 3 + 1


def fit_max_tokens(
    msgs: list[Message],
    tools: list[ToolSpec] | None,
    schema: type[BaseModel] | None,
    max_tokens: int,
) -> int:
    """Clamp max_tokens to LLM_MAX_REQUEST_TOKENS (input + output), when it's set. Some
    providers (e.g. Groq's free tier, 8k tokens/minute) reject any request whose input plus
    max_tokens exceeds the limit, so an unclamped request can never succeed."""
    ceiling = get_settings().llm_max_request_tokens
    if ceiling is None:
        return max_tokens
    room = ceiling - estimate_input_tokens(msgs, tools, schema)
    if room < MIN_OUTPUT_TOKENS:
        raise LLMBadRequestError(
            f"This request (~{ceiling - room:,} input tokens) is too large for "
            f"LLM_MAX_REQUEST_TOKENS={ceiling:,}.",
            hint="Shorten the brief or brand documents, raise the limit, or use a provider "
            "tier with a higher tokens-per-minute limit.",
        )
    return min(max_tokens, room)


class LLMService:
    def __init__(self, client_factory: Any = get_client) -> None:
        self._client_factory = client_factory  # injectable for tests
        self._limits: dict[str, asyncio.Semaphore] = {}

    def _limit(self, provider: str) -> asyncio.Semaphore:
        """Per-provider concurrency cap (LLM_MAX_CONCURRENCY). Excess calls wait their turn
        instead of all hitting a tokens-per-minute limit at once."""
        sem = self._limits.get(provider)
        if sem is None:
            sem = self._limits[provider] = asyncio.Semaphore(get_settings().llm_max_concurrency)
        return sem

    def client(self, route: Route) -> LLMClient:
        client: LLMClient = self._client_factory(route.provider)
        return client

    async def generate(
        self,
        ctx: CallContext,
        purpose: Purpose,
        prompt: RenderedPrompt | None = None,
        *,
        task: str,
        schema: type[T] | None = None,
        messages: list[Message] | None = None,
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        reasoning: Reasoning | None = None,
    ) -> tuple[LLMResult[T], uuid.UUID]:
        """`reasoning` hints how hard a reasoning model should think (ignored by models that
        don't support it). Low effort suits reviews and planning steps, and saves tokens."""
        route = resolve(purpose, ctx.ai)
        await check_spend_cap(ctx)
        msgs = _messages(prompt, messages)
        if temperature is None:
            temperature = get_settings().llm_temperature
        try:
            max_tokens = fit_max_tokens(msgs, tools, schema, max_tokens)
            async with self._limit(route.provider):
                result = await self.client(route).generate(
                    msgs,
                    model=route.model,
                    schema=schema,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    reasoning=reasoning,
                )
        except LLMError as exc:
            exc.provider = exc.provider or route.provider
            exc.model = exc.model or route.model
            usage = None
            if isinstance(exc.details, dict) and "usage" in exc.details:
                u = exc.details["usage"]
                usage = Usage(int(u.get("input", 0)), int(u.get("output", 0)))
            await _record(
                ctx=ctx, route=route, purpose=purpose, task=task, prompt=prompt,
                result=None, error=exc, messages=msgs, usage_on_error=usage,
            )  # fmt: skip
            raise
        call_id = await _record(
            ctx=ctx, route=route, purpose=purpose, task=task, prompt=prompt,
            result=result, error=None, messages=msgs,
        )  # fmt: skip
        return result, call_id

    async def stream(
        self,
        ctx: CallContext,
        purpose: Purpose,
        prompt: RenderedPrompt | None = None,
        *,
        task: str,
        messages: list[Message] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        route = resolve(purpose, ctx.ai)
        await check_spend_cap(ctx)
        msgs = _messages(prompt, messages)
        try:
            async with self._limit(route.provider):
                async for event in self.client(route).stream(
                    msgs,
                    model=route.model,
                    temperature=get_settings().llm_temperature,
                    max_tokens=max_tokens,
                ):
                    if isinstance(event, StreamDone):
                        await _record(
                            ctx=ctx, route=route, purpose=purpose, task=task, prompt=prompt,
                            result=event.result, error=None, messages=msgs,
                        )  # fmt: skip
                    yield event
        except LLMError as exc:
            await _record(
                ctx=ctx, route=route, purpose=purpose, task=task, prompt=prompt,
                result=None, error=exc, messages=msgs,
            )  # fmt: skip
            raise

    async def embed(
        self, ctx: CallContext, texts: list[str], *, task: str = "document"
    ) -> tuple[list[list[float]], Route]:
        route = resolve(Purpose.EMBEDDING, ctx.ai)
        dim = get_settings().embedding_dim
        started = datetime.now(UTC)
        try:
            async with self._limit(route.provider):
                vectors = await self.client(route).embed(
                    texts, model=route.model, task=task, dim=dim
                )
        except LLMError as exc:
            await _record(
                ctx=ctx, route=route, purpose=Purpose.EMBEDDING, task=f"embed_{task}",
                prompt=None, result=None, error=exc, messages=[],
            )  # fmt: skip
            raise
        # Embedding APIs don't all report tokens; estimate ~4 chars/token for the usage log.
        approx = Usage(input_tokens=sum(len(t) for t in texts) // 4)
        from launchpad.llm.pricing import estimate_cost

        result: LLMResult[Any] = LLMResult(
            text="", parsed=None, tool_calls=[], provider=route.provider, model=route.model,
            usage=approx, latency_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
            cost_usd=estimate_cost(route.provider, route.model, approx), request_id=None,
        )  # fmt: skip
        await _record(
            ctx=ctx, route=route, purpose=Purpose.EMBEDDING, task=f"embed_{task}",
            prompt=None, result=result, error=None, messages=[],
        )  # fmt: skip
        return vectors, route


llm = LLMService()
