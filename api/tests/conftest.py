from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from collections.abc import AsyncIterator

from cryptography.fernet import Fernet

# Configure before anything imports settings.
os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://launchpad:launchpad@localhost:5432/launchpad_test"
)
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 32)
os.environ.setdefault("TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_LOCAL_DIR"] = os.path.join(tempfile.gettempdir(), "launchpad-test-storage")

if sys.platform == "win32":  # psycopg (LangGraph's checkpointer) can't use the Proactor loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError
from sqlalchemy import text

from launchpad.db.base import Base
from launchpad.db.session import get_engine

_API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> None:
    """Run the real migrations once, so tests exercise the schema that ships."""
    cfg = Config(os.path.join(_API_DIR, "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    # Start from an empty schema (not `downgrade base`): leftover rows from a manual run could
    # make a lossy downgrade fail. CI checks downgrades separately on a fresh database.
    import psycopg

    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    command.upgrade(cfg, "head")


async def _reset_rate_limits() -> None:
    """Delete only our own rate-limit keys, only in the test Redis DB."""
    from launchpad.api.ratelimit import _redis

    try:
        keys = [k async for k in _redis().scan_iter("rl:*")]
        if keys:
            await _redis().delete(*keys)
    except (RedisError, OSError):
        pass  # No Redis locally: the limiter allows requests outside prod.


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    await _reset_rate_limits()
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
        # LangGraph's checkpoint tables live outside our metadata (created by saver.setup()).
        lg = await conn.scalar(text("SELECT to_regclass('checkpoints') IS NOT NULL"))
        if lg:
            await conn.execute(text("TRUNCATE checkpoints, checkpoint_writes, checkpoint_blobs"))


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from launchpad.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def authed(client: AsyncClient) -> AsyncClient:
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": "correct-horse-battery", "name": "Owner"},
    )
    assert r.status_code == 201, r.text
    client.headers["authorization"] = f"Bearer {r.json()['access_token']}"
    return client
