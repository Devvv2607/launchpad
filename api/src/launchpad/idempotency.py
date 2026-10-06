"""Idempotency keys for POST endpoints that start expensive work.

Clients send `Idempotency-Key: <uuid>` once per user action. The first request claims the key
(an INSERT .. ON CONFLICT DO NOTHING, so two simultaneous requests can't both win) and does the
work. A repeat with the same key gets the first request's result. Reusing a key for a different
request body is an error. If the first request fails, it releases the key so a retry can run.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.api.errors import AppError
from launchpad.models.idempotency import IdempotencyKey

TTL = timedelta(hours=24)


class IdempotencyMismatch(AppError):
    status_code = 422
    code = "idempotency_key_reused"


@dataclass(frozen=True)
class Claim:
    id: uuid.UUID
    first: bool  # True: this request does the work. False: replay the original.
    status: str
    response: dict[str, Any] | None


def request_hash(body: Any) -> str:
    raw = json.dumps(body, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


async def claim(
    db: AsyncSession, *, workspace_id: uuid.UUID, scope: str, key: str, body: Any
) -> Claim:
    digest = request_hash(body)
    # Keys expire after a day; an old row with the same key is cleared, not replayed.
    await db.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.workspace_id == workspace_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
            IdempotencyKey.created_at < datetime.now(UTC) - TTL,
        )
    )
    new_id = await db.scalar(
        insert(IdempotencyKey)
        .values(
            id=uuid.uuid4(), workspace_id=workspace_id, scope=scope, key=key,
            request_hash=digest, status="in_progress",
        )
        .on_conflict_do_nothing(index_elements=["workspace_id", "scope", "key"])
        .returning(IdempotencyKey.id)
    )  # fmt: skip
    await db.commit()
    if new_id is not None:
        return Claim(new_id, True, "in_progress", None)
    row = await db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.workspace_id == workspace_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
        )
    )
    if row is None:  # released between our insert and select: treat as fresh
        return await claim(db, workspace_id=workspace_id, scope=scope, key=key, body=body)
    if row.request_hash != digest:
        raise IdempotencyMismatch(
            "This Idempotency-Key was already used for a different request. "
            "Send a new key for a new action."
        )
    return Claim(row.id, False, row.status, row.response)


async def complete(db: AsyncSession, claim_id: uuid.UUID, response: dict[str, Any]) -> None:
    await db.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == claim_id)
        .values(status="done", response=response)
    )
    await db.commit()


async def release(db: AsyncSession, claim_id: uuid.UUID) -> None:
    """The original request failed: forget the key so a retry does the work."""
    await db.execute(delete(IdempotencyKey).where(IdempotencyKey.id == claim_id))
    await db.commit()


async def current(db: AsyncSession, claim_id: uuid.UUID) -> IdempotencyKey | None:
    row = await db.get(IdempotencyKey, claim_id, populate_existing=True)
    return row
