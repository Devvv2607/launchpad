from __future__ import annotations

import uuid

from sqlalchemy import text

from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import Platform
from launchpad.logging import redact_processor
from launchpad.models import ChannelConnection, User, Workspace


async def test_oauth_tokens_are_encrypted_at_rest() -> None:
    async with get_sessionmaker()() as db:
        user = User(email="t@example.com")
        db.add(user)
        await db.flush()
        ws = Workspace(owner_id=user.id, name="W", industry="food")
        db.add(ws)
        await db.flush()
        conn = ChannelConnection(
            workspace_id=ws.id,
            platform=Platform.INSTAGRAM,
            account_id="17841",
            access_token="EAAB-plaintext-token",
        )
        db.add(conn)
        await db.commit()
        conn_id = conn.id

        raw = await db.scalar(
            text("select access_token from channel_connections where id = :id"), {"id": conn_id}
        )
        assert raw and "plaintext" not in raw

        db.expire_all()
        loaded = await db.get(ChannelConnection, conn_id)
        assert loaded is not None and loaded.access_token == "EAAB-plaintext-token"


def test_log_redaction() -> None:
    event = {
        "event": "calling provider with Bearer abc.def.ghi",
        "api_key": "sk-live-123",
        "payload": {"access_token": "x", "nested": ["gsk_abcdefghijklmnop"]},
        "user_id": str(uuid.uuid4()),
    }
    out = redact_processor(None, "info", dict(event))
    assert out["api_key"] == "[REDACTED]"
    assert out["payload"]["access_token"] == "[REDACTED]"
    assert "[REDACTED]" in out["event"]
    assert out["payload"]["nested"] == ["[REDACTED]"]
    assert out["user_id"] == event["user_id"]
