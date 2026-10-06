"""Google Gemini adapter (Generative Language REST API, v1beta)."""

from __future__ import annotations

import math
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from launchpad.llm.base import LLMClient, tool_result_content
from launchpad.llm.errors import LLMOutputError, LLMRefusalError
from launchpad.llm.http import DEFAULT_TIMEOUT, post_json, stream_sse
from launchpad.llm.schema import inline_refs
from launchpad.llm.types import Message, RawCompletion, Reasoning, ToolCall, ToolSpec, Usage

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
EMBED_BATCH = 100
_TASK_TYPES = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}
_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}


class GeminiClient(LLMClient):
    provider = "gemini"
    supports_embeddings = True

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        http: httpx.AsyncClient | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        self._headers = {"x-goog-api-key": api_key}

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ request building

    @staticmethod
    def _contents(messages: list[Message]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        system = [m.content for m in messages if m.role == "system"]
        contents: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                part = {
                    "functionResponse": {
                        "name": m.name or "tool",
                        "response": {"result": tool_result_content(m.content)},
                        **({"id": m.tool_call_id} if m.tool_call_id else {}),
                    }
                }
                # Consecutive tool results belong in one user turn.
                if (
                    contents
                    and contents[-1]["role"] == "user"
                    and "functionResponse" in contents[-1]["parts"][-1]
                ):
                    contents[-1]["parts"].append(part)
                else:
                    contents.append({"role": "user", "parts": [part]})
                continue
            parts: list[dict[str, Any]] = []
            if m.content:
                parts.append({"text": m.content})
            for call in m.tool_calls:
                fc: dict[str, Any] = {"name": call.name, "args": call.arguments}
                if call.provider_data.get("id"):
                    fc["id"] = call.provider_data["id"]
                part = {"functionCall": fc}
                # Gemini 3 requires thought signatures to be echoed back with function calls.
                if call.provider_data.get("thought_signature"):
                    part["thoughtSignature"] = call.provider_data["thought_signature"]
                parts.append(part)
            contents.append({"role": "model" if m.role == "assistant" else "user", "parts": parts})
        system_instruction = {"parts": [{"text": "\n\n".join(system)}]} if system else None
        return system_instruction, contents

    def _payload(
        self,
        messages: list[Message],
        *,
        json_schema: dict[str, Any] | None,
        tools: list[ToolSpec] | None,
        temperature: float | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        system_instruction, contents = self._contents(messages)
        config: dict[str, Any] = {"maxOutputTokens": max_tokens}
        if temperature is not None:
            config["temperature"] = temperature
        if json_schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = inline_refs(json_schema)
        payload: dict[str, Any] = {"contents": contents, "generationConfig": config}
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parametersJsonSchema": inline_refs(t.parameters),
                        }
                        for t in tools
                    ]
                }
            ]
        return payload

    # ------------------------------------------------------------------ response parsing

    def _parse_response(
        self, body: dict[str, Any], model: str, request_id: str | None
    ) -> RawCompletion:
        usage = _usage(body)
        rid = body.get("responseId") or request_id
        feedback = body.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise LLMRefusalError(
                f"Gemini blocked the prompt ({feedback['blockReason']}).",
                provider=self.provider,
                model=model,
                request_id=rid,
                hint="Rephrase the brief; the provider's safety filter rejected it.",
            )
        candidates = body.get("candidates") or []
        if not candidates:
            raise LLMOutputError(
                "Gemini returned no candidates.",
                provider=self.provider,
                model=model,
                request_id=rid,
            )
        cand = candidates[0]
        finish = cand.get("finishReason")
        if finish in _BLOCKED:
            raise LLMRefusalError(
                f"Gemini stopped generating ({finish}).",
                provider=self.provider,
                model=model,
                request_id=rid,
                hint="Rephrase the brief; the provider's safety filter stopped the output.",
            )
        texts: list[str] = []
        calls: list[ToolCall] = []
        for part in (cand.get("content") or {}).get("parts") or []:
            if part.get("thought"):
                continue  # model reasoning summary, not output
            if "text" in part:
                texts.append(part["text"])
            if "functionCall" in part:
                fc = part["functionCall"]
                data: dict[str, Any] = {}
                if part.get("thoughtSignature"):
                    data["thought_signature"] = part["thoughtSignature"]
                if fc.get("id"):
                    data["id"] = fc["id"]
                calls.append(
                    ToolCall(
                        id=fc.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                        name=fc["name"],
                        arguments=fc.get("args") or {},
                        provider_data=data,
                    )
                )
        return RawCompletion(
            text="".join(texts), tool_calls=calls, usage=usage, request_id=rid, finish_reason=finish
        )

    # ------------------------------------------------------------------ primitives

    async def _complete(
        self,
        model: str,
        messages: list[Message],
        *,
        json_schema: dict[str, Any] | None,
        tools: list[ToolSpec] | None,
        temperature: float | None,
        max_tokens: int,
        reasoning: Reasoning | None = None,  # not mapped for this provider yet
    ) -> RawCompletion:
        payload = self._payload(
            messages,
            json_schema=json_schema,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        body, rid = await post_json(
            self._http,
            f"{self.base_url}/models/{model}:generateContent",
            payload,
            provider=self.provider,
            model=model,
            headers=self._headers,
            request_id_header="x-goog-request-id",
        )
        return self._parse_response(body, model, rid)

    async def _stream(
        self, model: str, messages: list[Message], *, temperature: float | None, max_tokens: int
    ) -> AsyncIterator[str | RawCompletion]:
        payload = self._payload(
            messages, json_schema=None, tools=None, temperature=temperature, max_tokens=max_tokens
        )
        text: list[str] = []
        usage, rid, finish = Usage(), None, None
        async for event, header_rid in stream_sse(
            self._http,
            f"{self.base_url}/models/{model}:streamGenerateContent?alt=sse",
            payload,
            provider=self.provider,
            model=model,
            headers=self._headers,
            request_id_header="x-goog-request-id",
        ):
            chunk = (
                self._parse_response(event, model, header_rid) if event.get("candidates") else None
            )
            if event.get("usageMetadata"):
                usage = _usage(event)
            rid = event.get("responseId") or header_rid or rid
            if chunk is not None:
                finish = chunk.finish_reason or finish
                if chunk.text:
                    text.append(chunk.text)
                    yield chunk.text
        yield RawCompletion(
            text="".join(text), tool_calls=[], usage=usage, request_id=rid, finish_reason=finish
        )

    async def _embed(
        self, model: str, texts: list[str], *, task: str, dim: int
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start : start + EMBED_BATCH]
            payload = {
                "requests": [
                    {
                        "model": f"models/{model}",
                        "content": {"parts": [{"text": t}]},
                        "taskType": _TASK_TYPES.get(task, "SEMANTIC_SIMILARITY"),
                        "outputDimensionality": dim,
                    }
                    for t in batch
                ]
            }
            body, _ = await post_json(
                self._http,
                f"{self.base_url}/models/{model}:batchEmbedContents",
                payload,
                provider=self.provider,
                model=model,
                headers=self._headers,
                request_id_header="x-goog-request-id",
            )
            got = [e["values"] for e in body.get("embeddings", [])]
            if len(got) != len(batch) or any(len(v) != dim for v in got):
                raise LLMOutputError(
                    f"Gemini returned {len(got)} embeddings of unexpected size "
                    f"for {len(batch)} inputs.",
                    provider=self.provider,
                    model=model,
                )
            # Truncated (non-3072) Gemini embeddings must be L2-normalised by the caller.
            vectors.extend(_normalise(v) for v in got)
        return vectors


def _usage(body: dict[str, Any]) -> Usage:
    meta = body.get("usageMetadata") or {}
    return Usage(
        input_tokens=int(meta.get("promptTokenCount", 0)),
        # Thinking tokens are billed as output.
        output_tokens=int(meta.get("candidatesTokenCount", 0))
        + int(meta.get("thoughtsTokenCount", 0)),
    )


def _normalise(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm else v
