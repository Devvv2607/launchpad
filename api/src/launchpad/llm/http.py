"""Shared HTTP plumbing for the httpx-based adapters (Gemini, OpenAI-compatible)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from launchpad.llm.errors import (
    LLMAuthError,
    LLMBadRequestError,
    LLMError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    model_not_found,
)

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


def retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    value = headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            from datetime import UTC, datetime

            return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError):
            return None


def error_message(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str):
            return err
    return str(body)[:300]


def map_status(
    *,
    provider: str,
    model: str,
    status: int,
    body: Any,
    headers: Mapping[str, str],
    request_id: str | None,
    model_env_var: str = "LLM_MODEL",
) -> LLMError:
    """Translate an HTTP error into a typed LLMError. Never includes credentials."""
    message = error_message(body)
    lowered = message.lower()
    common: dict[str, Any] = {"provider": provider, "model": model, "request_id": request_id}

    if status == 429:
        return LLMRateLimitError(
            f"{provider} rate limit reached: {message}",
            retry_after_s=retry_after_seconds(headers),
            hint="Wait a moment and retry, or lower usage. Free tiers have low per-minute limits.",
            **common,
        )
    if status in (401, 403) or "api key not valid" in lowered or "api_key_invalid" in lowered:
        return LLMAuthError(
            f"{provider} rejected the API key ({status}).",
            hint=f"Check {provider.upper()}_API_KEY in .env (missing, revoked or no access?).",
            **common,
        )
    if (
        status == 404
        or "model_not_found" in lowered
        or "decommissioned" in lowered
        or ("model" in lowered and ("not found" in lowered or "does not exist" in lowered))
    ):
        err = model_not_found(provider, model, model_env_var)
        err.request_id = request_id
        err.details = {"provider_message": message}
        return err
    if status == 408:
        return LLMTimeoutError(f"{provider} timed out.", **common)
    if status >= 500:
        return LLMProviderError(f"{provider} is having problems ({status}): {message}", **common)
    return LLMBadRequestError(f"{provider} rejected the request ({status}): {message}", **common)


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    *,
    provider: str,
    model: str,
    headers: Mapping[str, str] | None = None,
    request_id_header: str = "x-request-id",
) -> tuple[dict[str, Any], str | None]:
    try:
        resp = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise LLMTimeoutError(
            f"{provider} request timed out.", provider=provider, model=model
        ) from exc
    except httpx.TransportError as exc:
        raise LLMProviderError(
            f"Could not reach {provider}: {type(exc).__name__}", provider=provider, model=model
        ) from exc
    request_id = resp.headers.get(request_id_header)
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {"error": resp.text[:300]}
    if resp.status_code >= 400:
        raise map_status(
            provider=provider,
            model=model,
            status=resp.status_code,
            body=body,
            headers=resp.headers,
            request_id=request_id,
        )
    return body, request_id


async def stream_sse(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    *,
    provider: str,
    model: str,
    headers: Mapping[str, str] | None = None,
    request_id_header: str = "x-request-id",
) -> AsyncIterator[tuple[dict[str, Any], str | None]]:
    """Yield parsed JSON `data:` events from a server-sent-events response."""
    try:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            request_id = resp.headers.get(request_id_header)
            if resp.status_code >= 400:
                raw = await resp.aread()
                try:
                    body: Any = json.loads(raw)
                except json.JSONDecodeError:
                    body = {"error": raw[:300].decode(errors="replace")}
                raise map_status(
                    provider=provider,
                    model=model,
                    status=resp.status_code,
                    body=body,
                    headers=resp.headers,
                    request_id=request_id,
                )
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                yield json.loads(data), request_id
    except httpx.TimeoutException as exc:
        raise LLMTimeoutError(
            f"{provider} stream timed out.", provider=provider, model=model
        ) from exc
    except httpx.TransportError as exc:
        raise LLMProviderError(
            f"Lost connection to {provider}: {type(exc).__name__}", provider=provider, model=model
        ) from exc
