"""Fixed-window rate limiting backed by Redis (shared across API replicas).

If Redis is unreachable the limiter fails *closed* in prod and open in dev/test,
and says so in the logs — never silently.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from functools import lru_cache

import structlog
from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from launchpad.api.errors import RateLimited
from launchpad.config import get_settings

log = structlog.get_logger(__name__)


@lru_cache
def _redis() -> Redis:
    client: Redis = Redis.from_url(get_settings().redis_url, socket_timeout=0.5)
    return client


async def hit(key: str, limit: int, window_s: int) -> None:
    bucket = f"rl:{key}:{int(time.time()) // window_s}"
    try:
        pipe = _redis().pipeline()
        pipe.incr(bucket)
        pipe.expire(bucket, window_s)
        count, _ = await pipe.execute()
    except (RedisError, OSError) as exc:
        if get_settings().env == "prod":
            log.error("rate_limiter_unavailable", error=str(exc))
            raise RateLimited("Rate limiter unavailable; try again shortly.") from exc
        log.warning("rate_limiter_unavailable_allowing", error=str(exc))
        return
    if int(count) > limit:
        raise RateLimited(f"Too many requests. Limit is {limit} per {window_s}s.")


def rate_limit(scope: str, limit: int, window_s: int) -> Callable[[Request], Awaitable[None]]:
    """FastAPI dependency. Keys on the authenticated user if present, else client IP."""

    async def _dep(request: Request) -> None:
        who = getattr(request.state, "user_id", None) or (
            request.client.host if request.client else "anon"
        )
        await hit(f"{scope}:{who}", limit, window_s)

    return _dep
