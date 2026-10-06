"""Same request twice with the same Idempotency-Key → one result (generation and agent runs)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import JobKind
from launchpad.llm.errors import LLMAuthError
from launchpad.llm.types import Message, RawCompletion
from launchpad.models import AgentRun, ContentItem, LLMCall, ScheduledJob
from tests.content.fake_llm import THREE, ScriptedLLM, critique
from tests.content.test_engine import _parse_sse, env, use  # noqa: F401  (env is a fixture)

pytestmark = pytest.mark.usefixtures("env")
GEN = {"channel": "instagram_post", "brief": "Monsoon chai offer, ₹160", "n_variants": 3}


def _script(kind: str, prompt: str) -> str:
    if kind == "write":
        return THREE
    draft, _ = json.JSONDecoder().raw_decode(prompt.split("Draft (JSON):\n", 1)[1])
    return critique(9, draft)


class SlowLLM(ScriptedLLM):
    """Slow enough that a second request arrives while the first is still generating."""

    async def _complete(self, model: str, messages: list[Message], **kw: Any) -> RawCompletion:
        await asyncio.sleep(0.3)
        return await super()._complete(model, messages, **kw)


async def _ws(client: AsyncClient) -> str:
    r = await client.post("/api/v1/workspaces", json={"name": "Chai", "industry": "food"})
    return str(r.json()["id"])


async def _count(model: Any, *where: Any) -> int:
    async with get_sessionmaker()() as db:
        return int(await db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def _item_ids(text: str) -> list[str]:
    return [d["id"] for e, d in _parse_sse(text) if e == "item"]


async def test_generate_twice_with_the_same_key_generates_once(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, ScriptedLLM(_script))
    ws = await _ws(authed)
    url, headers = f"/api/v1/workspaces/{ws}/content/generate", {"idempotency-key": "k-1"}
    first = await authed.post(url, json=GEN, headers=headers)
    second = await authed.post(url, json=GEN, headers=headers)
    assert len(_item_ids(first.text)) == 3
    assert _item_ids(second.text) == _item_ids(first.text)  # replayed, not regenerated
    assert _parse_sse(second.text)[-1] == (
        "done",
        {"item_ids": _item_ids(first.text), "replayed": True},
    )
    assert await _count(ContentItem) == 3
    assert await _count(LLMCall, LLMCall.purpose == "write_content") == 1


async def test_concurrent_double_submit_generates_once(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, SlowLLM(_script))
    ws = await _ws(authed)
    url, headers = f"/api/v1/workspaces/{ws}/content/generate", {"idempotency-key": "k-2"}
    a, b = await asyncio.gather(
        authed.post(url, json=GEN, headers=headers), authed.post(url, json=GEN, headers=headers)
    )
    assert sorted(_item_ids(a.text)) == sorted(_item_ids(b.text))
    assert len(_item_ids(a.text)) == 3
    assert await _count(ContentItem) == 3
    assert await _count(LLMCall, LLMCall.purpose == "write_content") == 1


async def test_without_a_key_each_request_generates(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, ScriptedLLM(_script))
    ws = await _ws(authed)
    for _ in range(2):
        await authed.post(f"/api/v1/workspaces/{ws}/content/generate", json=GEN)
    assert await _count(ContentItem) == 6


async def test_reusing_a_key_for_a_different_request_is_rejected(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, ScriptedLLM(_script))
    ws = await _ws(authed)
    url, headers = f"/api/v1/workspaces/{ws}/content/generate", {"idempotency-key": "k-3"}
    await authed.post(url, json=GEN, headers=headers)
    r = await authed.post(url, json={**GEN, "brief": "Something else entirely"}, headers=headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "idempotency_key_reused"


async def test_a_failed_original_releases_the_key(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = await _ws(authed)
    url, headers = f"/api/v1/workspaces/{ws}/content/generate", {"idempotency-key": "k-4"}
    use(monkeypatch, ScriptedLLM(lambda k, p: LLMAuthError("Bad key", hint="Check .env")))
    failed = await authed.post(url, json=GEN, headers=headers)
    assert _parse_sse(failed.text)[-1][0] == "error"
    use(monkeypatch, ScriptedLLM(_script))
    retry = await authed.post(url, json=GEN, headers=headers)  # same key: runs for real now
    assert len(_item_ids(retry.text)) == 3


async def test_agent_run_twice_with_the_same_key_starts_one_run(authed: AsyncClient) -> None:
    ws = await _ws(authed)
    url = f"/api/v1/workspaces/{ws}/agent/runs"
    body, headers = {"message": "Plan a launch"}, {"idempotency-key": "run-1"}
    a, b = await asyncio.gather(
        authed.post(url, json=body, headers=headers), authed.post(url, json=body, headers=headers)
    )
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    assert await _count(AgentRun) == 1
    assert await _count(ScheduledJob, ScheduledJob.kind == JobKind.AGENT_RUN) == 1
    other = await authed.post(url, json={"message": "Different"}, headers=headers)
    assert other.status_code == 422
