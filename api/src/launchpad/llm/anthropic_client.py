"""Anthropic adapter, via the official `anthropic` SDK (Messages API).

The SDK's own retries are disabled (max_retries=0) so the shared retry/backoff policy in
`LLMClient` applies uniformly across providers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic
import httpx2

from launchpad.llm.base import LLMClient, tool_result_content
from launchpad.llm.capabilities import caps_for
from launchpad.llm.errors import (
    LLMAuthError,
    LLMBadRequestError,
    LLMError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMTimeoutError,
    model_not_found,
)
from launchpad.llm.http import retry_after_seconds
from launchpad.llm.schema import inline_refs, strict_schema
from launchpad.llm.types import Message, RawCompletion, ToolCall, ToolSpec, Usage

PROVIDER = "anthropic"


def _map_error(exc: Exception, model: str) -> LLMError:
    common: dict[str, Any] = {"provider": PROVIDER, "model": model}
    if isinstance(exc, anthropic.APIStatusError):
        common["request_id"] = exc.response.headers.get("request-id")
    # Most specific first: each SDK class means a different remedy.
    if isinstance(exc, anthropic.NotFoundError):
        return model_not_found(PROVIDER, model)
    if isinstance(exc, anthropic.RateLimitError):
        return LLMRateLimitError(
            "Anthropic rate limit reached.",
            retry_after_s=retry_after_seconds(exc.response.headers),
            hint="Wait a moment and retry.",
            **common,
        )
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return LLMAuthError(
            "Anthropic rejected the API key.",
            hint="Check ANTHROPIC_API_KEY in .env.",
            **common,
        )
    if isinstance(exc, anthropic.APITimeoutError):
        return LLMTimeoutError("Anthropic request timed out.", **common)
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMProviderError("Could not reach Anthropic.", **common)
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:  # includes 529 overloaded_error
            return LLMProviderError(f"Anthropic is having problems ({exc.status_code}).", **common)
        return LLMBadRequestError(f"Anthropic rejected the request: {exc.message}", **common)
    return LLMProviderError(f"Unexpected Anthropic error: {type(exc).__name__}", **common)


class AnthropicClient(LLMClient):
    provider = PROVIDER

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        http: httpx2.AsyncClient | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, base_url=base_url, max_retries=0, http_client=http, timeout=120.0
        )

    async def aclose(self) -> None:
        await self._client.close()

    @staticmethod
    def _messages(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": tool_result_content(m.content),
                }
                # All results for one assistant turn go back in a single user message.
                if (
                    out
                    and out[-1]["role"] == "user"
                    and isinstance(out[-1]["content"], list)
                    and out[-1]["content"][-1].get("type") == "tool_result"
                ):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif m.role == "assistant" and m.tool_calls:
                content: list[dict[str, Any]] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                content += [
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                    for c in m.tool_calls
                ]
                out.append({"role": "assistant", "content": content})
            else:
                out.append({"role": m.role, "content": m.content})
        return system, out

    def _params(
        self,
        model: str,
        messages: list[Message],
        *,
        json_schema: dict[str, Any] | None,
        tools: list[ToolSpec] | None,
        temperature: float | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        system, msgs = self._messages(messages)
        params: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": msgs}
        if system:
            params["system"] = system
        # Opus 5.5 / Sonnet 5.5 reject sampling params with a 400; only send where supported.
        if temperature is not None and caps_for(PROVIDER, model).temperature:
            params["temperature"] = temperature
        if json_schema is not None:
            params["output_config"] = {
                "format": {"type": "json_schema", "schema": strict_schema(json_schema)}
            }
        if tools:
            params["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": inline_refs(t.parameters),
                }
                for t in tools
            ]
        return params

    @staticmethod
    def _check_refusal(stop_reason: str | None, model: str, rid: str | None) -> None:
        if stop_reason == "refusal":
            raise LLMRefusalError(
                "Anthropic declined this request.",
                provider=PROVIDER,
                model=model,
                request_id=rid,
                hint="Rephrase the brief.",
            )

    async def _complete(
        self,
        model: str,
        messages: list[Message],
        *,
        json_schema: dict[str, Any] | None,
        tools: list[ToolSpec] | None,
        temperature: float | None,
        max_tokens: int,
    ) -> RawCompletion:
        params = self._params(
            model,
            messages,
            json_schema=json_schema,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            resp = await self._client.messages.create(**params)
        except anthropic.APIError as exc:
            raise _map_error(exc, model) from exc
        rid = resp._request_id
        self._check_refusal(resp.stop_reason, model, rid)
        texts, calls = [], []
        for block in resp.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))
        return RawCompletion(
            text="".join(texts),
            tool_calls=calls,
            usage=Usage(resp.usage.input_tokens, resp.usage.output_tokens),
            request_id=rid,
            finish_reason=resp.stop_reason,
        )

    async def _stream(
        self, model: str, messages: list[Message], *, temperature: float | None, max_tokens: int
    ) -> AsyncIterator[str | RawCompletion]:
        params = self._params(
            model,
            messages,
            json_schema=None,
            tools=None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            async with self._client.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except anthropic.APIError as exc:
            raise _map_error(exc, model) from exc
        self._check_refusal(final.stop_reason, model, final._request_id)
        yield RawCompletion(
            text="".join(b.text for b in final.content if b.type == "text"),
            tool_calls=[],
            usage=Usage(final.usage.input_tokens, final.usage.output_tokens),
            request_id=final._request_id,
            finish_reason=final.stop_reason,
        )
