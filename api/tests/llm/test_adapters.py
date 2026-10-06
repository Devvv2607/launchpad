"""Adapter contract tests with mocked HTTP. Every provider must behave identically:
same retries, same typed errors, same structured-output repair policy."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import httpx2
import pytest
from pydantic import BaseModel, Field

from launchpad.llm.anthropic_client import AnthropicClient
from launchpad.llm.base import LLMClient
from launchpad.llm.errors import (
    LLMAuthError,
    LLMBadRequestError,
    LLMModelNotFoundError,
    LLMOutputError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRefusalError,
)
from launchpad.llm.gemini import GeminiClient
from launchpad.llm.openai_compat import GroqClient, OpenAIClient
from launchpad.llm.types import Message, StreamDelta, StreamDone, ToolSpec

PROVIDERS = ["gemini", "groq", "openai", "anthropic"]
MODEL = {
    "gemini": "gemini-3.6-flash",
    "groq": "openai/gpt-oss-120b",
    "openai": "gpt-6-luna",
    "anthropic": "claude-sonnet-5-5",
}


class Caption(BaseModel):
    caption: str = Field(min_length=5)
    hashtags: list[str]


Reply = tuple[int, Any, dict[str, str]]


# ----------------------------------------------------------------------------- fixtures


def ok_body(provider: str, text: str) -> Any:
    if provider == "gemini":
        return {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 40,
                "thoughtsTokenCount": 10,
            },
            "responseId": "gem-resp-1",
        }
    if provider == "anthropic":
        return {
            "id": "msg_1", "type": "message", "role": "assistant", "model": MODEL[provider],
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 100, "output_tokens": 50},
        }  # fmt: skip
    return {
        "id": "chatcmpl-1",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


def error_body(provider: str, kind: str) -> Reply:
    if provider == "gemini":
        return {
            "rate": (429, {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}}, {"retry-after": "0"}),
            # Gemini reports a bad key as 400 INVALID_ARGUMENT, not 401.
            "auth": (400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}, {}),
            "model": (404, {"error": {"code": 404, "message": "models/gemini-9 is not found for API version v1beta", "status": "NOT_FOUND"}}, {}),
            "server": (503, {"error": {"code": 503, "message": "The model is overloaded", "status": "UNAVAILABLE"}}, {}),
        }[kind]  # fmt: skip
    if provider == "anthropic":
        return {
            "rate": (429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}, {"retry-after": "0"}),
            "auth": (401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}, {}),
            "model": (404, {"type": "error", "error": {"type": "not_found_error", "message": "model: claude-9"}}, {}),
            "server": (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}, {}),
        }[kind]  # fmt: skip
    return {
        "rate": (429, {"error": {"message": "Rate limit reached", "type": "tokens", "code": "rate_limit_exceeded"}}, {"retry-after": "0"}),
        "auth": (401, {"error": {"message": "Invalid API Key", "type": "invalid_request_error", "code": "invalid_api_key"}}, {}),
        "model": (404, {"error": {"message": "The model `x` does not exist", "type": "invalid_request_error", "code": "model_not_found"}}, {}),
        "server": (503, {"error": {"message": "Service Unavailable", "type": "internal_server_error"}}, {}),
    }[kind]  # fmt: skip


@dataclass
class Harness:
    client: LLMClient
    requests: list[dict[str, Any]] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)


def make(provider: str, replies: list[Reply]) -> Harness:
    queue = list(replies)
    h_requests: list[dict[str, Any]] = []
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    def respond(body: bytes) -> Reply:
        h_requests.append(json.loads(body) if body else {})
        assert queue, "unexpected extra request"
        return queue.pop(0)

    kw: dict[str, Any] = {"max_retries": 3, "sleep": fake_sleep}
    client: LLMClient
    if provider == "anthropic":

        def handler2(req: httpx2.Request) -> httpx2.Response:
            status, body, headers = respond(req.content)
            return httpx2.Response(
                status, json=body, headers={"request-id": "req_ant_1", **headers}
            )

        http2 = httpx2.AsyncClient(transport=httpx2.MockTransport(handler2))
        client = AnthropicClient("test-key", base_url="https://anthropic.test", http=http2, **kw)
    else:

        def handler(req: httpx.Request) -> httpx.Response:
            status, body, headers = respond(req.content)
            return httpx.Response(status, json=body, headers=headers)

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        cls: Callable[..., LLMClient] = {
            "gemini": GeminiClient,
            "groq": GroqClient,
            "openai": OpenAIClient,
        }[provider]
        client = cls("test-key", http=http, **kw)
    return Harness(client, h_requests, sleeps)


MSGS = [Message("system", "You write captions."), Message("user", "Monsoon chai offer")]
VALID = json.dumps({"caption": "Cutting chai, rainy day, 20% off.", "hashtags": ["#MumbaiRains"]})


# ----------------------------------------------------------------------------- tests


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_success_text_usage_and_cost(provider: str) -> None:
    h = make(provider, [(200, ok_body(provider, "Hello Bandra"), {})])
    r = await h.client.generate(MSGS, model=MODEL[provider])
    assert r.text == "Hello Bandra"
    assert r.provider == provider and r.model == MODEL[provider]
    assert r.usage.input_tokens == 100
    assert r.usage.output_tokens == 50  # Gemini: candidates + thoughts
    assert r.request_id
    # Every test model here has a price entry except the unverified OpenAI ones.
    assert (r.cost_usd is None) == (provider == "openai")


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_rate_limit_then_success_honours_retry_after(provider: str) -> None:
    h = make(provider, [error_body(provider, "rate"), (200, ok_body(provider, "ok"), {})])
    r = await h.client.generate(MSGS, model=MODEL[provider])
    assert r.text == "ok"
    assert len(h.requests) == 2
    assert h.sleeps == [0.0]  # Retry-After: 0 honoured instead of exponential backoff


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_server_errors_backoff_then_give_up(provider: str) -> None:
    h = make(provider, [error_body(provider, "server")] * 4)
    with pytest.raises(LLMProviderError):
        await h.client.generate(MSGS, model=MODEL[provider])
    assert len(h.requests) == 4  # 1 + max_retries
    assert len(h.sleeps) == 3 and all(s > 0 for s in h.sleeps)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_auth_error_is_not_retried(provider: str) -> None:
    h = make(provider, [error_body(provider, "auth")])
    with pytest.raises(LLMAuthError) as exc:
        await h.client.generate(MSGS, model=MODEL[provider])
    assert len(h.requests) == 1 and h.sleeps == []
    assert exc.value.hint and "API_KEY" in exc.value.hint
    assert "test-key" not in str(exc.value) + str(exc.value.hint)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_model_not_found_tells_user_to_check_env(provider: str) -> None:
    h = make(provider, [error_body(provider, "model")])
    with pytest.raises(LLMModelNotFoundError) as exc:
        await h.client.generate(MSGS, model=MODEL[provider])
    assert len(h.requests) == 1
    assert exc.value.hint and ".env" in exc.value.hint


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_structured_output_valid_first_time(provider: str) -> None:
    h = make(provider, [(200, ok_body(provider, VALID), {})])
    r = await h.client.generate(MSGS, model=MODEL[provider], schema=Caption)
    assert isinstance(r.parsed, Caption) and r.parsed.hashtags == ["#MumbaiRains"]
    assert r.attempts == 1


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_malformed_json_is_repaired_once(provider: str) -> None:
    h = make(
        provider,
        [
            (200, ok_body(provider, '{"caption": "hi"'), {}),  # truncated JSON
            (200, ok_body(provider, VALID), {}),
        ],
    )
    r = await h.client.generate(MSGS, model=MODEL[provider], schema=Caption)
    assert r.parsed is not None and r.attempts == 2
    assert r.usage.input_tokens == 200  # both attempts counted
    repair_request = json.dumps(h.requests[1])
    assert "did not match the required JSON schema" in repair_request
    assert "not valid JSON" in repair_request  # the actual error is fed back


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_invalid_twice_raises_typed_error_not_fallback(provider: str) -> None:
    bad = json.dumps({"caption": "no", "hashtags": "not-a-list"})
    h = make(provider, [(200, ok_body(provider, bad), {}), (200, ok_body(provider, bad), {})])
    with pytest.raises(LLMOutputError) as exc:
        await h.client.generate(MSGS, model=MODEL[provider], schema=Caption)
    assert len(h.requests) == 2
    assert "caption" in exc.value.details["errors"]


async def test_gemini_request_shape_and_fenced_json() -> None:
    fenced = f"```json\n{VALID}\n```"
    h = make("gemini", [(200, ok_body("gemini", fenced), {})])
    r = await h.client.generate(MSGS, model="gemini-3.6-flash", schema=Caption, temperature=0.4)
    assert r.parsed is not None
    req = h.requests[0]
    assert req["systemInstruction"]["parts"][0]["text"] == "You write captions."
    assert req["contents"] == [{"role": "user", "parts": [{"text": "Monsoon chai offer"}]}]
    cfg = req["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseJsonSchema"]["properties"]["hashtags"]["type"] == "array"
    assert cfg["temperature"] == 0.4


async def test_gemini_tool_calls_round_trip_thought_signature() -> None:
    body = {
        "candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "get_brand_context", "args": {"query": "tone"}}, "thoughtSignature": "sig-abc"},
        ]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
    }  # fmt: skip
    h = make("gemini", [(200, body, {}), (200, ok_body("gemini", "done"), {})])
    tool = ToolSpec(
        "get_brand_context",
        "Brand info",
        {"type": "object", "properties": {"query": {"type": "string"}}},
    )
    r = await h.client.generate(MSGS, model="gemini-3.6-flash", tools=[tool])
    call = r.tool_calls[0]
    assert call.name == "get_brand_context" and call.arguments == {"query": "tone"}
    follow = [
        *MSGS,
        Message("assistant", tool_calls=[call]),
        Message("tool", '{"voice":"warm"}', tool_call_id=call.id, name=call.name),
    ]
    await h.client.generate(follow, model="gemini-3.6-flash", tools=[tool])
    model_turn, tool_turn = h.requests[1]["contents"][1:]
    assert model_turn["parts"][0]["thoughtSignature"] == "sig-abc"
    assert tool_turn["parts"][0]["functionResponse"]["name"] == "get_brand_context"


async def test_gemini_safety_block_is_a_refusal() -> None:
    body = {
        "candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}],
        "usageMetadata": {},
    }
    h = make("gemini", [(200, body, {})])
    with pytest.raises(LLMRefusalError):
        await h.client.generate(MSGS, model="gemini-3.6-flash")


async def test_groq_uses_strict_schema_for_gpt_oss_and_json_mode_for_llama() -> None:
    h = make("groq", [(200, ok_body("groq", VALID), {}), (200, ok_body("groq", VALID), {})])
    await h.client.generate(MSGS, model="openai/gpt-oss-120b", schema=Caption)
    await h.client.generate(MSGS, model="llama-3.3-70b-versatile", schema=Caption)
    strict, json_mode = h.requests
    rf = strict["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False
    assert json_mode["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in json_mode["messages"][0]["content"]  # schema moved into the prompt


async def test_openai_reasoning_models_omit_temperature() -> None:
    h = make("openai", [(200, ok_body("openai", "x"), {})])
    await h.client.generate(MSGS, model="gpt-6-luna", temperature=0.9, max_tokens=500)
    assert "temperature" not in h.requests[0]
    assert h.requests[0]["max_completion_tokens"] == 500


async def test_anthropic_omits_temperature_on_sonnet_5_5_and_uses_output_config() -> None:
    h = make("anthropic", [(200, ok_body("anthropic", VALID), {})])
    await h.client.generate(MSGS, model="claude-sonnet-5-5", schema=Caption, temperature=0.9)
    req = h.requests[0]
    assert "temperature" not in req  # 400s on Sonnet 5.5 / Opus 5.5
    assert req["system"] == "You write captions."
    fmt = req["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False


async def test_anthropic_refusal_stop_reason() -> None:
    body = ok_body("anthropic", "")
    body["stop_reason"] = "refusal"
    h = make("anthropic", [(200, body, {})])
    with pytest.raises(LLMRefusalError):
        await h.client.generate(MSGS, model="claude-sonnet-5-5")


@pytest.mark.parametrize("provider", ["gemini", "groq"])
async def test_stream_yields_deltas_then_usage(provider: str) -> None:
    if provider == "gemini":
        events = [
            {"candidates": [{"content": {"parts": [{"text": "Chai "}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "time"}]}, "finishReason": "STOP"}],
             "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 2}},
        ]  # fmt: skip
    else:
        events = [
            {"id": "c1", "choices": [{"delta": {"content": "Chai "}}]},
            {"id": "c1", "choices": [{"delta": {"content": "time"}, "finish_reason": "stop"}]},
            {"id": "c1", "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
        ]
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=sse.encode(), headers={"content-type": "text/event-stream"}
        )

    cls = GeminiClient if provider == "gemini" else GroqClient
    client = cls("k", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    out = [e async for e in client.stream(MSGS, model=MODEL[provider])]
    deltas = [e.text for e in out if isinstance(e, StreamDelta)]
    done = [e for e in out if isinstance(e, StreamDone)]
    assert deltas == ["Chai ", "time"]
    assert done[0].result.text == "Chai time" and done[0].result.usage.input_tokens == 7


async def test_gemini_embeddings_are_normalised_and_dimension_checked() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["requests"][0]["outputDimensionality"] == 4
        assert body["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
        return httpx.Response(
            200, json={"embeddings": [{"values": [3, 0, 4, 0]} for _ in body["requests"]]}
        )

    client = GeminiClient("k", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    vecs = await client.embed(["a", "b"], model="gemini-embedding-001", task="query", dim=4)
    assert vecs == [[0.6, 0.0, 0.8, 0.0]] * 2

    def wrong_dim(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]}]})

    client = GeminiClient("k", http=httpx.AsyncClient(transport=httpx.MockTransport(wrong_dim)))
    with pytest.raises(LLMOutputError):
        await client.embed(["a"], model="gemini-embedding-001", dim=4)


async def test_long_retry_after_is_surfaced_not_waited() -> None:
    h = make("groq", [(429, {"error": {"message": "daily limit"}}, {"retry-after": "3600"})])
    with pytest.raises(LLMRateLimitError) as exc:
        await h.client.generate(MSGS, model="openai/gpt-oss-120b")
    assert exc.value.retry_after_s == 3600 and h.sleeps == []


async def test_groq_strict_schema_rejection_goes_through_repair() -> None:
    rejected = json.dumps({"caption": "Monsoon chai"})  # missing hashtags
    groq_400 = {
        "error": {
            "message": "Generated JSON does not match the expected schema.",
            "type": "invalid_request_error",
            "code": "json_validate_failed",
            "failed_generation": rejected,
        }
    }
    h = make("groq", [(400, groq_400, {}), (200, ok_body("groq", VALID), {})])
    r = await h.client.generate(MSGS, model="openai/gpt-oss-120b", schema=Caption)
    assert r.parsed is not None and r.attempts == 2
    repair = h.requests[1]["messages"]
    assert repair[-2] == {"role": "assistant", "content": rejected}
    assert "hashtags" in repair[-1]["content"]  # the real validation error is fed back


async def test_other_groq_400s_still_raise() -> None:
    body = {"error": {"message": "context too long", "code": "context_length_exceeded"}}
    h = make("groq", [(400, body, {})])
    with pytest.raises(LLMBadRequestError):
        await h.client.generate(MSGS, model="openai/gpt-oss-120b", schema=Caption)


async def test_reasoning_effort_is_sent_only_to_models_that_support_it() -> None:
    h = make("groq", [(200, ok_body("groq", VALID), {}), (200, ok_body("groq", VALID), {})])
    await h.client.generate(MSGS, model="openai/gpt-oss-20b", schema=Caption, reasoning="low")
    await h.client.generate(MSGS, model="llama-3.3-70b-versatile", schema=Caption, reasoning="low")
    gpt_oss, llama = h.requests
    assert gpt_oss["reasoning_effort"] == "low"
    assert "reasoning_effort" not in llama


def test_strict_schema_keeps_fields_named_title_or_default() -> None:
    from pydantic import BaseModel as _BM

    from launchpad.agent.graph import PlanOut
    from launchpad.llm.schema import strict_schema

    class Odd(_BM):
        title: str
        default: int

    s = strict_schema(Odd.model_json_schema())
    assert set(s["properties"]) == {"title", "default"}
    assert s["required"] == ["title", "default"]
    assert "title" not in s  # the schema's own title annotation is still dropped
    step = strict_schema(PlanOut.model_json_schema())["properties"]["steps"]["items"]
    assert step["required"] == ["title", "tool"]  # this field was missing (planner regression)
