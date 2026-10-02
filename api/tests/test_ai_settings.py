from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from launchpad.config import get_settings
from launchpad.db.session import get_sessionmaker
from launchpad.models import LLMCall


@pytest.fixture(autouse=True)
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", SecretStr("g-test"))
    monkeypatch.setattr(s, "groq_api_key", None)
    monkeypatch.setattr(s, "anthropic_api_key", None)
    monkeypatch.setattr(s, "openai_api_key", None)
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "llm_model", "gemini-3.6-flash")
    monkeypatch.setattr(s, "llm_fast_model", None)
    monkeypatch.setattr(s, "embedding_provider", None)


async def test_settings_show_effective_routes_and_only_keyed_providers(authed: AsyncClient) -> None:
    ws = (await authed.post("/api/v1/workspaces", json={"name": "C", "industry": "food"})).json()[
        "id"
    ]
    body = (await authed.get(f"/api/v1/workspaces/{ws}/ai-settings")).json()
    assert body["configured_providers"] == ["gemini"]
    assert {m["provider"] for m in body["catalog"]} == {"gemini"}
    eff = body["effective"]
    assert eff["writing"] == {
        "provider": "gemini",
        "model": "gemini-3.6-flash",
        "source": "env",
        "error": None,
    }
    assert (
        eff["critique"]["model"] == "gemini-3.6-flash"
    )  # fast model unset -> falls back to LLM_MODEL
    assert eff["embedding"]["source"] == "unconfigured" and "EMBEDDING" in eff["embedding"]["error"]

    r = await authed.put(
        f"/api/v1/workspaces/{ws}/ai-settings",
        json={"routes": {"critique": {"provider": "groq", "model": "openai/gpt-oss-20b"}}},
    )
    assert r.status_code == 400 and "no API key" in r.json()["error"]["message"]

    r = await authed.put(
        f"/api/v1/workspaces/{ws}/ai-settings",
        json={
            "routes": {"critique": {"provider": "gemini", "model": "gemini-3.1-flash-lite"}},
            "daily_spend_cap_usd": 0.5,
        },
    )
    assert r.status_code == 200
    assert r.json()["effective"]["critique"]["source"] == "workspace"
    assert r.json()["daily_spend_cap_usd"] == 0.5


async def test_usage_aggregates_real_calls_and_flags_unknown_prices(authed: AsyncClient) -> None:
    ws = (await authed.post("/api/v1/workspaces", json={"name": "C", "industry": "food"})).json()[
        "id"
    ]
    async with get_sessionmaker()() as db:
        for purpose, cost, status in [
            ("write_content", Decimal("0.010"), "ok"),
            ("write_content", Decimal("0.020"), "ok"),
            ("critique_content", None, "ok"),  # unknown price
            ("critique_content", None, "error"),
        ]:
            db.add(LLMCall(workspace_id=uuid.UUID(ws), provider="gemini", model="gemini-3.6-flash",
                           purpose=purpose, status=status, tokens_in=100, tokens_out=50, cost_usd=cost))  # fmt: skip
        await db.commit()
    u = (await authed.get(f"/api/v1/workspaces/{ws}/usage")).json()
    assert u["totals"]["calls"] == 4 and u["totals"]["errors"] == 1
    assert u["totals"]["unknown_cost_calls"] == 1
    assert abs(u["totals"]["cost_usd"] - 0.03) < 1e-9 and abs(u["today_spent_usd"] - 0.03) < 1e-9
    assert u["by_task"][0]["key"] == "write_content"
    assert u["by_model"][0]["key"] == "gemini:gemini-3.6-flash" and len(u["by_day"]) == 1
    assert u["daily_cap_usd"] == get_settings().daily_spend_cap_usd

    empty = (await authed.get(f"/api/v1/workspaces/{ws}/usage?month=2025-01")).json()
    assert empty["totals"]["calls"] == 0 and empty["by_day"] == []
    assert (await authed.get(f"/api/v1/workspaces/{ws}/usage?month=bad")).status_code == 400
