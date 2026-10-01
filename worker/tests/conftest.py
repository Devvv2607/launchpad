from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from cryptography.fernet import Fernet

os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://launchpad:launchpad@localhost:5432/launchpad_test"
)
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 32)
os.environ.setdefault("TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from launchpad.db.base import Base
from launchpad.db.session import get_engine

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "api" / "alembic.ini"


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> None:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
