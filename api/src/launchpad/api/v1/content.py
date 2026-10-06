from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad import idempotency as idem
from launchpad.api.deps import DB, CurrentUser, CurrentWorkspace
from launchpad.api.errors import AppError, Conflict, NotFound
from launchpad.api.ratelimit import rate_limit
from launchpad.content.context import build_brand_context
from launchpad.content.engine import (
    email_payload,
    main_text,
    parse_content,
    revalidate,
    suggest_hashtags,
    write_content,
)
from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import Channel, ContentStatus
from launchpad.llm.errors import LLMError
from launchpad.llm.service import CallContext
from launchpad.models import Campaign, ContentItem, Workspace
from launchpad.schemas.content import (
    ContentEditIn,
    ContentItemOut,
    GenerateIn,
    HashtagsIn,
    HashtagsOut,
    ViolationOut,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/workspaces/{workspace_id}/content", tags=["content"])

EDITABLE = {
    ContentStatus.DRAFT,
    ContentStatus.IN_REVIEW,
    ContentStatus.APPROVED,
    ContentStatus.FAILED,
}


def item_out(item: ContentItem) -> ContentItemOut:
    out = ContentItemOut.model_validate(item)
    violations = (item.generation or {}).get("violations") or []
    out.violations = [ViolationOut.model_validate(v) for v in violations if isinstance(v, dict)]
    out.blocked = any(v.get("severity") == "error" for v in violations if isinstance(v, dict))
    return out


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n".encode()


def _error_payload(exc: Exception, request: Request) -> dict[str, Any]:
    rid = getattr(request.state, "request_id", None)
    if isinstance(exc, LLMError):
        return {
            "code": exc.code, "message": exc.message, "hint": exc.hint,
            "provider": exc.provider, "model": exc.model, "request_id": rid,
            **({"retry_after_s": exc.retry_after_s} if hasattr(exc, "retry_after_s") else {}),
        }  # fmt: skip
    if isinstance(exc, AppError):
        return {"code": exc.code, "message": exc.message, "request_id": rid}
    log.exception("generation_failed")
    return {
        "code": "internal_error",
        "message": "Generation failed unexpectedly.",
        "request_id": rid,
    }


@router.post(
    "/generate",
    dependencies=[Depends(rate_limit("generate", 10, 60))],
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-sent events"}},
)
async def generate_content(
    body: GenerateIn,
    request: Request,
    ws: CurrentWorkspace,
    user: CurrentUser,
    db: DB,
    idempotency_key: str | None = Header(default=None, max_length=128),
) -> StreamingResponse:
    """Streams progress as SSE: `step`, `variant`, `item`, then `done` or `error`.

    With an `Idempotency-Key` header, a repeat of the same request (double submit, network or
    proxy retry) doesn't generate again: it waits for the original and streams its saved items.
    """
    if body.channel == Channel.POSTER:
        raise AppError("Posters are designed in the poster studio, not generated as text.")
    campaign_goal = None
    if body.campaign_id:
        campaign = await db.get(Campaign, body.campaign_id)
        if campaign is None or campaign.workspace_id != ws.id:
            raise NotFound("Campaign not found.")
        campaign_goal = campaign.goal.value
    ws_id, user_id = ws.id, user.id
    claim: idem.Claim | None = None
    if idempotency_key:
        claim = await idem.claim(
            db, workspace_id=ws.id, scope="content.generate", key=idempotency_key,
            body=body.model_dump(mode="json"),
        )  # fmt: skip
        if not claim.first:
            return _sse_response(_replay(claim.id, request))

    async def events() -> AsyncIterator[bytes]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def progress(evt: dict[str, Any]) -> None:
            await queue.put((str(evt.pop("type")), evt))

        async def run() -> None:
            # Own session: the request-scoped one may close before a streamed body finishes.
            async with get_sessionmaker()() as session:
                workspace = await session.get(Workspace, ws_id)
                assert workspace is not None
                ctx = CallContext.for_workspace(workspace, user_id)
                try:
                    results = await write_content(
                        session, workspace, ctx, channel=body.channel, brief=body.brief,
                        n_variants=body.n_variants, critique=body.critique,
                        campaign_id=body.campaign_id, campaign_goal=campaign_goal,
                        progress=progress,
                    )  # fmt: skip
                    ids = [r.item_id for r in results if r.item_id]
                    for item in await _items_in_order(session, ids):
                        await queue.put(("item", item_out(item).model_dump(mode="json")))
                    if claim is not None:
                        await idem.complete(session, claim.id, {"item_ids": [str(i) for i in ids]})
                    await queue.put(("done", {"item_ids": [str(i) for i in ids]}))
                except BaseException as exc:
                    if claim is not None:  # failed or cancelled: a retry may run it again
                        async with get_sessionmaker()() as cleanup:
                            await idem.release(cleanup, claim.id)
                    if not isinstance(exc, Exception):
                        raise
                    await queue.put(("error", _error_payload(exc, request)))
                finally:
                    await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                if msg is None:
                    break
                yield _sse(*msg)
        finally:
            if not task.done():  # client went away: stop spending tokens
                task.cancel()

    return _sse_response(events())


def _sse_response(stream: AsyncIterator[bytes]) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"cache-control": "no-cache, no-transform", "x-accel-buffering": "no"},
    )


async def _items_in_order(session: AsyncSession, ids: list[uuid.UUID]) -> list[ContentItem]:
    items = list(await session.scalars(select(ContentItem).where(ContentItem.id.in_(ids))))
    order = {i: n for n, i in enumerate(ids)}
    return sorted(items, key=lambda it: order[it.id])


REPLAY_WAIT_S = 15 * 60


async def _replay(claim_id: uuid.UUID, request: Request) -> AsyncIterator[bytes]:
    """A repeat of an in-flight or finished generation: wait for the original, then stream its
    saved items. Never starts a second generation."""
    label = "Already generating this request; waiting for it to finish"
    yield _sse("step", {"key": "replay", "status": "running", "label": label})
    started = time.monotonic()
    last_ping = started
    while time.monotonic() - started < REPLAY_WAIT_S:
        async with get_sessionmaker()() as session:
            row = await idem.current(session, claim_id)
            if row is None:
                yield _sse("error", {
                    "code": "original_request_failed",
                    "message": "The original request for this generation failed.",
                    "hint": "Try again; it will start a fresh generation.",
                    "request_id": getattr(request.state, "request_id", None),
                })  # fmt: skip
                return
            if row.status == "done" and row.response is not None:
                ids = [uuid.UUID(i) for i in row.response.get("item_ids", [])]
                for item in await _items_in_order(session, ids):
                    yield _sse("item", item_out(item).model_dump(mode="json"))
                yield _sse("done", {"item_ids": [str(i) for i in ids], "replayed": True})
                return
        if time.monotonic() - last_ping >= 15:
            yield b": keep-alive\n\n"
            last_ping = time.monotonic()
        await asyncio.sleep(1)
    yield _sse("error", {"code": "timeout", "message": "The original request is taking too long."})


@router.get("", response_model=list[ContentItemOut])
async def list_content(
    ws: CurrentWorkspace,
    db: DB,
    status_: list[ContentStatus] | None = Query(default=None, alias="status"),
    channel: Channel | None = None,
    variant_group: uuid.UUID | None = None,
    limit: int = Query(default=50, le=200),
) -> list[ContentItemOut]:
    q = select(ContentItem).where(ContentItem.workspace_id == ws.id)
    if status_:
        q = q.where(ContentItem.status.in_(status_))
    if channel:
        q = q.where(ContentItem.channel == channel)
    if variant_group:
        q = q.where(ContentItem.variant_group == variant_group)
    rows = await db.scalars(
        q.order_by(ContentItem.created_at.desc(), ContentItem.variant_label).limit(limit)
    )
    return [item_out(i) for i in rows]


async def _item(db: DB, ws: Workspace, item_id: uuid.UUID) -> ContentItem:
    item = await db.get(ContentItem, item_id)
    if item is None or item.workspace_id != ws.id:
        raise NotFound("Content not found.")
    return item


@router.get("/{item_id}", response_model=ContentItemOut)
async def get_content(item_id: uuid.UUID, ws: CurrentWorkspace, db: DB) -> ContentItemOut:
    return item_out(await _item(db, ws, item_id))


@router.patch("/{item_id}", response_model=ContentItemOut)
async def edit_content(
    item_id: uuid.UUID, body: ContentEditIn, ws: CurrentWorkspace, user: CurrentUser, db: DB
) -> ContentItemOut:
    item = await _item(db, ws, item_id)
    if item.status not in EDITABLE:
        raise Conflict(f"{item.status.value.title()} content can't be edited.")
    try:
        parsed = parse_content(item.channel, body.content)
    except ValidationError as exc:
        raise AppError(
            "That content doesn't match the channel's format.", details=exc.errors()
        ) from exc
    content = parsed.model_dump()
    violations = revalidate(item.channel, content)
    payload = dict(content)
    if item.channel == Channel.EMAIL:
        bctx = await build_brand_context(db, ws, CallContext.for_workspace(ws, user.id), query=None)
        payload["rendered"] = await email_payload(db, ws, bctx, content)
    item.payload = payload
    item.body = main_text(item.channel, content)
    item.hashtags = list(content.get("hashtags", []))
    if body.title is not None:
        item.title = body.title
    history = list((item.generation or {}).get("edits", []))
    history.append({"by": str(user.id), "violations": len(violations)})
    item.generation = {
        **(item.generation or {}),
        "violations": violations,
        "edits": history,
        "edited": True,
    }
    if item.status == ContentStatus.APPROVED:
        item.status = ContentStatus.DRAFT  # edits after approval need re-approval
    await db.commit()
    await db.refresh(item)
    return item_out(item)


@router.post(
    "/{item_id}/regenerate",
    response_model=ContentItemOut,
    dependencies=[Depends(rate_limit("generate", 10, 60))],
)
async def regenerate_variant(
    item_id: uuid.UUID, ws: CurrentWorkspace, user: CurrentUser, db: DB
) -> ContentItemOut:
    item = await _item(db, ws, item_id)
    if item.status not in (ContentStatus.DRAFT, ContentStatus.IN_REVIEW, ContentStatus.FAILED):
        raise Conflict("Only drafts can be regenerated.")
    gen = item.generation or {}
    brief = str(gen.get("brief") or item.body)
    [result] = await write_content(
        db, ws, CallContext.for_workspace(ws, user.id), channel=item.channel, brief=brief,
        n_variants=1, keep_angle=item.title or gen.get("angle"), save=False,
    )  # fmt: skip
    previous = {k: gen.get(k) for k in ("iterations", "violations", "llm_call_ids")}
    payload = dict(result.content)
    if item.channel == Channel.EMAIL:
        bctx = await build_brand_context(db, ws, CallContext.for_workspace(ws, user.id), query=None)
        payload["rendered"] = await email_payload(db, ws, bctx, result.content)
    scores = result.final_scores
    item.payload = payload
    item.body = main_text(item.channel, result.content)
    item.hashtags = list(result.content.get("hashtags", []))
    item.critique_score = round(sum(scores.values()) / len(scores)) if scores else None
    item.generation = {
        **gen,
        "hook": result.hook,
        "rationale": result.rationale,
        "iterations": [it.__dict__ for it in result.iterations],
        "violations": result.violations,
        "llm_call_ids": result.llm_call_ids,
        "history": [*gen.get("history", []), previous],
    }
    await db.commit()
    await db.refresh(item)
    return item_out(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_content(item_id: uuid.UUID, ws: CurrentWorkspace, db: DB) -> None:
    item = await _item(db, ws, item_id)
    if item.status in (ContentStatus.SCHEDULED, ContentStatus.PUBLISHED):
        raise Conflict("Scheduled or published content can't be deleted.")
    await db.delete(item)
    await db.commit()


@router.post(
    "/hashtags",
    response_model=HashtagsOut,
    dependencies=[Depends(rate_limit("hashtags", 20, 60))],
)
async def hashtags(
    body: HashtagsIn, ws: CurrentWorkspace, user: CurrentUser, db: DB
) -> HashtagsOut:
    buckets = await suggest_hashtags(
        db, ws, CallContext.for_workspace(ws, user.id), channel=body.channel, content_text=body.text
    )
    return HashtagsOut(**buckets)
