"""Provider-neutral LLM client.

Adapters implement three small primitives (`_complete`, `_stream`, `_embed`). This base
class owns everything policy-related so every provider behaves the same:

* Transport retries: exponential backoff + jitter on 429 / 5xx / timeouts only, honouring
  Retry-After. Auth, model-not-found and other 4xx errors are never retried.
* Structured output: parse + Pydantic-validate; on failure retry ONCE with the validation
  error fed back to the model; if that fails too, raise `LLMOutputError`. Never fall back
  to template content.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from launchpad.llm.errors import (
    LLMError,
    LLMNotConfiguredError,
    LLMOutputError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMToolCallRejected,
)
from launchpad.llm.pricing import estimate_cost
from launchpad.llm.schema import extract_json, json_schema_for
from launchpad.llm.types import (
    LLMResult,
    Message,
    RawCompletion,
    Reasoning,
    StreamDelta,
    StreamDone,
    StreamEvent,
    ToolSpec,
    Usage,
)

log = structlog.get_logger("launchpad.llm")

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

RETRYABLE = (LLMRateLimitError, LLMProviderError, LLMTimeoutError)

TOOL_REPAIR_PROMPT = (
    "[system] Your last tool call was rejected before it ran: {error}\n"
    "Call the tool again with arguments that match its schema exactly, or reply without tools."
)

REPAIR_PROMPT = (
    "Your previous reply did not match the required JSON schema.\n"
    "Errors:\n{errors}\n\n"
    "Reply again with ONLY a JSON object that fixes every error above. "
    "No prose, no markdown fences."
)


class LLMClient(ABC):
    provider: str
    supports_embeddings = False

    def __init__(
        self,
        *,
        max_retries: int = 3,
        backoff_base_s: float = 1.0,
        backoff_cap_s: float = 20.0,
        max_retry_after_s: float = 60.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.max_retry_after_s = max_retry_after_s
        self._sleep = sleep  # injectable so tests don't actually wait

    # ------------------------------------------------------------------ adapter API

    @abstractmethod
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
    ) -> RawCompletion: ...

    @abstractmethod
    def _stream(
        self,
        model: str,
        messages: list[Message],
        *,
        temperature: float | None,
        max_tokens: int,
    ) -> AsyncIterator[str | RawCompletion]:
        """Yield text deltas, then exactly one final RawCompletion (with usage)."""

    async def _embed(
        self, model: str, texts: list[str], *, task: str, dim: int
    ) -> list[list[float]]:
        raise LLMNotConfiguredError(f"{self.provider} does not provide embeddings.")

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release HTTP resources."""

    # ------------------------------------------------------------------ public API

    async def generate(
        self,
        messages: list[Message],
        *,
        model: str,
        schema: type[T] | None = None,
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        reasoning: Reasoning | None = None,
    ) -> LLMResult[T]:
        if schema is not None and tools:
            raise ValueError("Structured output and tool calling can't be combined in one call.")
        started = time.perf_counter()
        json_schema = json_schema_for(schema) if schema else None

        async def call(msgs: list[Message]) -> RawCompletion:
            return await self._with_retries(
                lambda: self._complete(
                    model,
                    msgs,
                    json_schema=json_schema,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    reasoning=reasoning,
                ),
                model=model,
            )

        attempts = 1
        try:
            raw = await call(messages)
        except LLMToolCallRejected as rejected:
            # The provider rejected the model's tool call against the schema. Tell the model why
            # and let it try once more, as the tools node would for arguments it validates itself.
            attempts = 2
            log.warning("llm_tool_call_rejected_retrying", provider=self.provider, model=model,
                        error=rejected.message[:500])  # fmt: skip
            raw = await call(
                [
                    *messages,
                    Message(role="user", content=TOOL_REPAIR_PROMPT.format(error=rejected.message)),
                ]
            )
        usage, parsed = raw.usage, None
        if schema is not None:
            try:
                parsed = self._parse(schema, raw.text)
            except (ValueError, ValidationError) as first_error:
                attempts = 2
                log.warning(
                    "llm_output_invalid_retrying",
                    provider=self.provider,
                    model=model,
                    error=_format_errors(first_error)[:500],
                )
                repair = [
                    *messages,
                    Message(role="assistant", content=raw.text),
                    Message(
                        role="user",
                        content=REPAIR_PROMPT.format(errors=_format_errors(first_error)),
                    ),
                ]
                raw = await call(repair)
                usage = usage + raw.usage
                try:
                    parsed = self._parse(schema, raw.text)
                except (ValueError, ValidationError) as second_error:
                    raise LLMOutputError(
                        "The model returned invalid structured output twice.",
                        provider=self.provider,
                        model=model,
                        request_id=raw.request_id,
                        hint="Try again, or switch this task to a stronger model in Settings → AI.",
                        details={
                            "errors": _format_errors(second_error),
                            "raw_excerpt": raw.text[:500],
                            "usage": {"input": usage.input_tokens, "output": usage.output_tokens},
                        },
                    ) from second_error

        return LLMResult(
            text=raw.text,
            parsed=parsed,
            tool_calls=raw.tool_calls,
            provider=self.provider,
            model=model,
            usage=usage,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=estimate_cost(self.provider, model, usage),
            request_id=raw.request_id,
            attempts=attempts,
            finish_reason=raw.finish_reason,
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Stream text. Retries only happen before the first token is emitted."""
        started = time.perf_counter()
        attempt = 0
        while True:
            emitted = False
            try:
                async for item in self._stream(
                    model, messages, temperature=temperature, max_tokens=max_tokens
                ):
                    if isinstance(item, str):
                        emitted = True
                        yield StreamDelta(item)
                    else:
                        yield StreamDone(
                            LLMResult(
                                text=item.text,
                                parsed=None,
                                tool_calls=item.tool_calls,
                                provider=self.provider,
                                model=model,
                                usage=item.usage,
                                latency_ms=int((time.perf_counter() - started) * 1000),
                                cost_usd=estimate_cost(self.provider, model, item.usage),
                                request_id=item.request_id,
                                finish_reason=item.finish_reason,
                            )
                        )
                return
            except RETRYABLE as exc:
                attempt += 1
                if emitted or attempt > self.max_retries:
                    raise
                await self._backoff(exc, attempt, model)

    async def embed(
        self, texts: list[str], *, model: str, task: str = "document", dim: int = 768
    ) -> list[list[float]]:
        return await self._with_retries(
            lambda: self._embed(model, texts, task=task, dim=dim), model=model
        )

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _parse(schema: type[T], text: str) -> T:
        return schema.model_validate(extract_json(text))

    async def _with_retries(self, fn: Callable[[], Awaitable[R]], *, model: str) -> R:
        attempt = 0
        while True:
            try:
                return await fn()
            except RETRYABLE as exc:
                attempt += 1
                if attempt > self.max_retries:
                    raise
                await self._backoff(exc, attempt, model)

    async def _backoff(self, exc: LLMError, attempt: int, model: str) -> None:
        retry_after = getattr(exc, "retry_after_s", None)
        if retry_after is not None:
            if retry_after > self.max_retry_after_s:
                raise exc  # don't block a request for minutes; surface it
            delay = retry_after
        else:
            delay = min(self.backoff_base_s * 2 ** (attempt - 1), self.backoff_cap_s)
            delay *= random.uniform(0.5, 1.5)  # noqa: S311 - jitter, not crypto
        log.warning(
            "llm_retry",
            provider=self.provider,
            model=model,
            attempt=attempt,
            error=exc.code,
            delay_s=round(delay, 2),
        )
        await self._sleep(delay)


def _format_errors(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "\n".join(
            f"- {'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in exc.errors()
        )
    return f"- {exc}"


def tool_result_content(value: Any) -> str:
    """Serialise a tool result for the model."""
    return value if isinstance(value, str) else json.dumps(value, default=str)


def zero_usage() -> Usage:
    return Usage()
