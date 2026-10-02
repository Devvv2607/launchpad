"""Live provider tests. Skipped unless RUN_LIVE_TESTS=1 (they cost a little money).

    RUN_LIVE_TESTS=1 pytest -m live tests/llm/test_live.py -v

They validate exactly what mocks can't: that the configured model IDs exist, that our
request shapes are accepted, and that structured output / tools / embeddings work for real.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from launchpad.config import get_settings
from launchpad.llm.base import LLMClient
from launchpad.llm.errors import LLMModelNotFoundError
from launchpad.llm.gemini import GeminiClient
from launchpad.llm.openai_compat import GroqClient
from launchpad.llm.types import Message, StreamDelta, StreamDone, ToolSpec

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1"),
]


def _key(provider: str) -> str:
    secret = getattr(get_settings(), f"{provider}_api_key")
    value = secret.get_secret_value() if secret else ""
    if not value:
        pytest.skip(f"{provider.upper()}_API_KEY not set")
    return value


def _models(provider: str) -> dict[str, str]:
    """Model IDs to exercise, from env (LIVE_<PROVIDER>_MODEL...) with documented defaults."""
    if provider == "gemini":
        return {
            "chat": os.environ.get("LIVE_GEMINI_MODEL", "gemini-3.6-flash"),
            "fast": os.environ.get("LIVE_GEMINI_FAST_MODEL", "gemini-3.1-flash-lite"),
            "embed": os.environ.get("LIVE_GEMINI_EMBED_MODEL", "gemini-embedding-001"),
        }
    return {
        "chat": os.environ.get("LIVE_GROQ_MODEL", "openai/gpt-oss-120b"),
        "fast": os.environ.get("LIVE_GROQ_FAST_MODEL", "openai/gpt-oss-20b"),
    }


def _client(provider: str) -> LLMClient:
    return GeminiClient(_key(provider)) if provider == "gemini" else GroqClient(_key(provider))


async def _list_models(provider: str) -> set[str]:
    key = _key(provider)
    async with httpx.AsyncClient(timeout=30) as http:
        if provider == "gemini":
            ids: set[str] = set()
            token = None
            while True:
                params: dict[str, Any] = {"pageSize": 1000}
                if token:
                    params["pageToken"] = token
                r = await http.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params=params,
                    headers={"x-goog-api-key": key},
                )
                r.raise_for_status()
                body = r.json()
                ids |= {m["name"].removeprefix("models/") for m in body.get("models", [])}
                token = body.get("nextPageToken")
                if not token:
                    return ids
        r = await http.get(
            "https://api.groq.com/openai/v1/models", headers={"authorization": f"Bearer {key}"}
        )
        r.raise_for_status()
        return {m["id"] for m in r.json()["data"]}


class Caption(BaseModel):
    caption: str = Field(min_length=10, max_length=300)
    hashtags: list[str] = Field(min_length=2, max_length=8)


PROVIDERS = ["gemini", "groq"]
MSGS = [
    Message("system", "You write short Instagram captions for a Mumbai cafe."),
    Message("user", "Write one caption for a monsoon cutting-chai offer, with 3 hashtags."),
]


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_configured_model_ids_exist(provider: str) -> None:
    available = await _list_models(provider)
    missing = [m for m in _models(provider).values() if m not in available]
    assert not missing, f"{provider} doesn't list {missing}; check .env.example IDs"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_plain_generation(provider: str) -> None:
    client = _client(provider)
    r = await client.generate(MSGS, model=_models(provider)["fast"], max_tokens=1024)
    assert len(r.text) > 10
    assert r.usage.input_tokens > 0 and r.usage.output_tokens > 0
    assert r.cost_usd is not None


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_structured_output(provider: str) -> None:
    client = _client(provider)
    r = await client.generate(
        MSGS, model=_models(provider)["chat"], schema=Caption, max_tokens=2048
    )
    assert isinstance(r.parsed, Caption)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_streaming(provider: str) -> None:
    client = _client(provider)
    events = [
        e async for e in client.stream(MSGS, model=_models(provider)["fast"], max_tokens=1024)
    ]
    deltas = [e for e in events if isinstance(e, StreamDelta)]
    done = [e for e in events if isinstance(e, StreamDone)]
    assert deltas and len(done) == 1
    assert done[0].result.text == "".join(d.text for d in deltas)
    assert done[0].result.usage.output_tokens > 0


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_tool_call_round_trip(provider: str) -> None:
    client = _client(provider)
    tool = ToolSpec(
        "get_brand_context",
        "Look up the brand's voice and offers. Always call this before writing.",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    )
    msgs = [*MSGS, Message("user", "First call get_brand_context for 'voice'.")]
    model = _models(provider)["chat"]
    r = await client.generate(msgs, model=model, tools=[tool], max_tokens=2048)
    assert r.tool_calls, f"expected a tool call, got text: {r.text[:200]}"
    call = r.tool_calls[0]
    follow = [
        *msgs,
        Message("assistant", r.text, tool_calls=[call]),
        Message(
            "tool",
            '{"voice": "warm, bookish", "offer": "20% off chai"}',
            tool_call_id=call.id,
            name=call.name,
        ),
    ]
    r2 = await client.generate(follow, model=model, tools=[tool], max_tokens=2048)
    assert r2.text and not r2.tool_calls


async def test_gemini_embeddings_768() -> None:
    client = GeminiClient(_key("gemini"))
    dim = get_settings().embedding_dim
    vecs = await client.embed(
        ["cutting chai", "filter coffee"], model=_models("gemini")["embed"], dim=dim
    )
    assert len(vecs) == 2 and all(len(v) == dim for v in vecs)
    assert abs(sum(x * x for x in vecs[0]) - 1.0) < 1e-3  # normalised


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_unknown_model_gives_actionable_error(provider: str) -> None:
    client = _client(provider)
    with pytest.raises(LLMModelNotFoundError) as exc:
        await client.generate(MSGS, model="definitely-not-a-model-2026")
    assert ".env" in (exc.value.hint or "")
