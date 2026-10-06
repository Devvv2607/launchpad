"""Adapter for OpenAI-compatible Chat Completions APIs: Groq and OpenAI."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from launchpad.llm.base import LLMClient, tool_result_content
from launchpad.llm.capabilities import caps_for
from launchpad.llm.errors import LLMBadRequestError, LLMOutputError, LLMRefusalError
from launchpad.llm.http import DEFAULT_TIMEOUT, post_json, stream_sse
from launchpad.llm.schema import inline_refs, strict_schema
from launchpad.llm.types import Message, RawCompletion, Reasoning, ToolCall, ToolSpec, Usage

JSON_MODE_INSTRUCTION = (
    "Respond with a single JSON object that conforms to this JSON Schema. "
    "Output only the JSON, with no markdown fences or commentary.\n\nSchema:\n{schema}"
)


class OpenAICompatClient(LLMClient):
    provider = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str,
        http: httpx.AsyncClient | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        self._headers = {"authorization": f"Bearer {api_key}"}

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _messages(messages: list[Message], extra_system: str | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id,
                        "content": tool_result_content(m.content),
                    }
                )
            elif m.role == "assistant" and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content or None,
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                            }
                            for c in m.tool_calls
                        ],
                    }
                )
            else:
                out.append({"role": m.role, "content": m.content})
        if extra_system:
            out.insert(0, {"role": "system", "content": extra_system})
        return out

    def _payload(
        self,
        model: str,
        messages: list[Message],
        *,
        json_schema: dict[str, Any] | None,
        tools: list[ToolSpec] | None,
        temperature: float | None,
        max_tokens: int,
        stream: bool = False,
        reasoning: Reasoning | None = None,
    ) -> dict[str, Any]:
        caps = caps_for(self.provider, model)
        extra_system = None
        payload: dict[str, Any] = {"model": model, caps.max_tokens_field: max_tokens}
        if reasoning is not None and caps.reasoning_effort:
            payload["reasoning_effort"] = reasoning
        if temperature is not None and caps.temperature:
            payload["temperature"] = temperature
        if json_schema is not None:
            if caps.structured in ("strict", "json_schema"):
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": json_schema.get("title", "output"),
                        "schema": strict_schema(json_schema)
                        if caps.structured == "strict"
                        else inline_refs(json_schema),
                        "strict": caps.structured == "strict",
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}
                extra_system = JSON_MODE_INSTRUCTION.format(
                    schema=json.dumps(inline_refs(json_schema), indent=1)
                )
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": inline_refs(t.parameters),
                    },
                }
                for t in tools
            ]
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        payload["messages"] = self._messages(messages, extra_system)
        return payload

    async def _complete(
        self,
        model: str,
        messages: list[Message],
        *,
        json_schema: dict[str, Any] | None,
        tools: list[ToolSpec] | None,
        temperature: float | None,
        max_tokens: int,
        reasoning: Reasoning | None = None,
    ) -> RawCompletion:
        try:
            body, rid = await post_json(
                self._http,
                f"{self.base_url}/chat/completions",
                self._payload(
                    model, messages, json_schema=json_schema, tools=tools,
                    temperature=temperature, max_tokens=max_tokens, reasoning=reasoning,
                ),
                provider=self.provider,
                model=model,
                headers=self._headers,
            )  # fmt: skip
        except LLMBadRequestError as exc:
            rejected = _schema_rejection(exc) if json_schema is not None else None
            if rejected is None:
                raise
            # Strict-mode providers (Groq) reject non-conforming JSON server-side. Hand the
            # rejected output back so the normal validate-then-repair path handles it, instead
            # of failing on the first imperfect generation. Usage isn't reported for rejections.
            return RawCompletion(rejected, [], Usage(0, 0), exc.request_id, "schema_rejected")
        choices = body.get("choices") or []
        if not choices:
            raise LLMOutputError(
                f"{self.provider} returned no choices.",
                provider=self.provider,
                model=model,
                request_id=rid,
            )
        choice = choices[0]
        msg = choice.get("message") or {}
        if msg.get("refusal"):
            raise LLMRefusalError(
                f"{self.provider} declined: {msg['refusal']}",
                provider=self.provider,
                model=model,
                request_id=rid,
            )
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError as exc:
                raise LLMOutputError(
                    f"Tool call '{fn.get('name')}' had malformed JSON arguments.",
                    provider=self.provider, model=model, request_id=rid,
                ) from exc  # fmt: skip
            calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
        return RawCompletion(
            text=msg.get("content") or "",
            tool_calls=calls,
            usage=_usage(body),
            request_id=body.get("id") or rid,
            finish_reason=choice.get("finish_reason"),
        )

    async def _stream(
        self, model: str, messages: list[Message], *, temperature: float | None, max_tokens: int
    ) -> AsyncIterator[str | RawCompletion]:
        text: list[str] = []
        usage, rid, finish = Usage(), None, None
        async for event, header_rid in stream_sse(
            self._http,
            f"{self.base_url}/chat/completions",
            self._payload(
                model, messages, json_schema=None, tools=None,
                temperature=temperature, max_tokens=max_tokens, stream=True,
            ),
            provider=self.provider,
            model=model,
            headers=self._headers,
        ):  # fmt: skip
            rid = event.get("id") or header_rid or rid
            if event.get("usage"):
                usage = _usage(event)
            # Groq reports usage under x_groq.usage on the final chunk.
            if (event.get("x_groq") or {}).get("usage"):
                usage = _usage(event["x_groq"])
            for choice in event.get("choices") or []:
                delta = (choice.get("delta") or {}).get("content")
                finish = choice.get("finish_reason") or finish
                if delta:
                    text.append(delta)
                    yield delta
        yield RawCompletion(
            text="".join(text), tool_calls=[], usage=usage, request_id=rid, finish_reason=finish
        )


def _usage(body: dict[str, Any]) -> Usage:
    u = body.get("usage") or {}
    return Usage(int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)))


class GroqClient(OpenAICompatClient):
    provider = "groq"

    def __init__(
        self, api_key: str, *, base_url: str = "https://api.groq.com/openai/v1", **kw: Any
    ) -> None:
        super().__init__(api_key, base_url=base_url, **kw)


class OpenAIClient(OpenAICompatClient):
    provider = "openai"
    supports_embeddings = True

    def __init__(
        self, api_key: str, *, base_url: str = "https://api.openai.com/v1", **kw: Any
    ) -> None:
        super().__init__(api_key, base_url=base_url, **kw)

    async def _embed(
        self, model: str, texts: list[str], *, task: str, dim: int
    ) -> list[list[float]]:
        body, _ = await post_json(
            self._http,
            f"{self.base_url}/embeddings",
            {"model": model, "input": texts, "dimensions": dim},
            provider=self.provider,
            model=model,
            headers=self._headers,
        )
        data = sorted(body.get("data", []), key=lambda d: d["index"])
        return [d["embedding"] for d in data]


def _schema_rejection(exc: LLMBadRequestError) -> str | None:
    """The provider's rejected generation, when a 400 means "output didn't match the schema"."""
    details = exc.details if isinstance(exc.details, dict) else {}
    err = details.get("provider_error") or {}
    failed = err.get("failed_generation")
    if err.get("code") == "json_validate_failed" and isinstance(failed, str):
        return failed
    return None
