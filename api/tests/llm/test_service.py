from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from launchpad.config import get_settings
from launchpad.db.session import get_sessionmaker
from launchpad.llm.base import LLMClient
from launchpad.llm.errors import LLMAuthError, LLMNotConfiguredError, SpendCapExceededError
from launchpad.llm.registry import AISettings, PurposeRoute, resolve
from launchpad.llm.service import CallContext, LLMService
from launchpad.llm.types import Message, Purpose, RawCompletion, ToolSpec, Usage
from launchpad.models import LLMCall, User, Workspace
from launchpad.prompts import load_prompt


class Out(BaseModel):
    answer: str


class FakeClient(LLMClient):
    provider = "gemini"

    def __init__(self, replies: list[RawCompletion | Exception]) -> None:
        super().__init__(max_retries=0)
        self.replies = replies
        self.models: list[str] = []

    async def _complete(self, model: str, messages: list[Message], **_: Any) -> RawCompletion:
        self.models.append(model)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def _stream(
        self, model: str, messages: list[Message], **_: Any
    ) -> AsyncIterator[str | RawCompletion]:
        raise NotImplementedError
        yield ""  # pragma: no cover


def raw(text: str, tin: int = 1000, tout: int = 1000) -> RawCompletion:
    return RawCompletion(text=text, tool_calls=[], usage=Usage(tin, tout), request_id="rid-1")


@pytest.fixture
def env_models(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "llm_model", "gemini-3.6-flash")
    monkeypatch.setattr(s, "llm_fast_model", "gemini-3.1-flash-lite")
    monkeypatch.setattr(s, "daily_spend_cap_usd", 1.0)
    monkeypatch.setattr(s, "log_llm_payloads", False)


async def _ctx(**ai: Any) -> CallContext:
    async with get_sessionmaker()() as db:
        user = User(email=f"{uuid.uuid4().hex}@example.com")
        db.add(user)
        await db.flush()
        ws = Workspace(owner_id=user.id, name="Cafe", industry="food", ai_settings=ai)
        db.add(ws)
        await db.commit()
        return CallContext.for_workspace(ws, user.id)


async def _calls(ws_id: uuid.UUID) -> list[LLMCall]:
    async with get_sessionmaker()() as db:
        return list(await db.scalars(select(LLMCall).where(LLMCall.workspace_id == ws_id)))


def test_routing_env_defaults_and_fast_model(env_models: None) -> None:
    assert resolve(Purpose.WRITING).model == "gemini-3.6-flash"
    assert resolve(Purpose.CRITIQUE).model == "gemini-3.1-flash-lite"


def test_routing_never_silently_falls_back(
    env_models: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)
    ai = AISettings(
        routes={Purpose.WRITING: PurposeRoute(provider="anthropic", model="claude-sonnet-5-5")}
    )
    with pytest.raises(LLMNotConfiguredError) as exc:
        resolve(Purpose.WRITING, ai)
    assert "ANTHROPIC_API_KEY" in (exc.value.hint or "")

    monkeypatch.setattr(get_settings(), "llm_model", None)
    with pytest.raises(LLMNotConfiguredError):
        resolve(Purpose.WRITING)


async def test_successful_call_is_logged_with_prompt_version(env_models: None) -> None:
    ctx = await _ctx()
    fake = FakeClient([raw('{"answer": "chai"}')])
    svc = LLMService(client_factory=lambda _p: fake)
    prompt = load_prompt("smoke_test").render(topic="chai")

    result, call_id = await svc.generate(ctx, Purpose.WRITING, prompt, task="smoke", schema=Out)
    assert result.parsed == Out(answer="chai")
    [row] = await _calls(ctx.workspace_id)
    assert row.id == call_id and row.status == "ok" and row.purpose == "smoke"
    assert row.prompt_name == "smoke_test" and row.prompt_version == prompt.version
    assert row.model == "gemini-3.6-flash" and row.tokens_in == 1000
    assert row.cost_usd == Decimal("0.004500")  # (1000*0.75 + 1000*3.75) / 1e6
    assert row.payload is None  # LOG_LLM_PAYLOADS defaults to false
    assert row.user_id == ctx.user_id


async def test_failed_call_is_logged_and_reraised(env_models: None) -> None:
    ctx = await _ctx()
    fake = FakeClient([LLMAuthError("bad key", hint="Check GEMINI_API_KEY")])
    svc = LLMService(client_factory=lambda _p: fake)
    with pytest.raises(LLMAuthError):
        await svc.generate(ctx, Purpose.WRITING, messages=[Message("user", "hi")], task="smoke")
    [row] = await _calls(ctx.workspace_id)
    assert row.status == "error" and row.error_code == "llm_auth" and row.cost_usd is None


async def test_payloads_stored_only_when_enabled(
    env_models: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "log_llm_payloads", True)
    ctx = await _ctx()
    svc = LLMService(client_factory=lambda _p: FakeClient([raw("hello")]))
    await svc.generate(ctx, Purpose.WRITING, messages=[Message("user", "secret brief")], task="t")
    [row] = await _calls(ctx.workspace_id)
    assert row.payload == {
        "messages": [{"role": "user", "content": "secret brief"}],
        "output": "hello",
    }


async def test_daily_spend_cap_blocks_with_clear_error(env_models: None) -> None:
    ctx = await _ctx()
    # 100k in + 200k out on gemini-3.6-flash = 0.075 + 0.75 = $0.825 per call; cap is $1.
    fake = FakeClient([raw("a", 100_000, 200_000), raw("b", 100_000, 200_000), raw("c")])
    svc = LLMService(client_factory=lambda _p: fake)
    await svc.generate(ctx, Purpose.WRITING, messages=[Message("user", "x")], task="t")
    await svc.generate(ctx, Purpose.WRITING, messages=[Message("user", "x")], task="t")  # $1.65 now
    with pytest.raises(SpendCapExceededError) as exc:
        await svc.generate(ctx, Purpose.WRITING, messages=[Message("user", "x")], task="t")
    assert "Settings" in (exc.value.hint or "")
    assert len(fake.replies) == 1  # blocked before calling the provider


async def test_workspace_cap_override(env_models: None) -> None:
    ctx = await _ctx(daily_spend_cap_usd=0)
    svc = LLMService(client_factory=lambda _p: FakeClient([raw("a")]))
    with pytest.raises(SpendCapExceededError):
        await svc.generate(ctx, Purpose.WRITING, messages=[Message("user", "x")], task="t")


async def test_workspace_route_override_uses_its_model(
    env_models: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "groq_api_key", SecretStr("gsk-test"))
    ctx = await _ctx(routes={"critique": {"provider": "groq", "model": "openai/gpt-oss-20b"}})
    used: list[str] = []
    fake = FakeClient([raw("ok")])

    def factory(provider: str) -> LLMClient:
        used.append(provider)
        return fake

    svc = LLMService(client_factory=factory)
    await svc.generate(ctx, Purpose.CRITIQUE, messages=[Message("user", "x")], task="critique")
    assert used == ["groq"] and fake.models == ["openai/gpt-oss-20b"]


def test_tool_and_schema_cannot_combine() -> None:
    import asyncio

    fake = FakeClient([])
    with pytest.raises(ValueError):
        asyncio.run(
            fake.generate(
                [Message("user", "x")],
                model="m",
                schema=Out,
                tools=[ToolSpec("t", "d", {"type": "object"})],
            )
        )
