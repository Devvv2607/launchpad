"""Typed LLM errors. Each carries a stable `code` (mapped to an HTTP status and a UI message)
and a human `hint` telling the user how to fix it. Nothing here ever degrades into fake content.
"""

from __future__ import annotations

from typing import Any


class LLMError(Exception):
    code = "llm_error"
    http_status = 502
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        hint: str | None = None,
        request_id: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.model = model
        self.hint = hint
        self.request_id = request_id
        self.details = details


class LLMNotConfiguredError(LLMError):
    code = "llm_not_configured"
    http_status = 503


class LLMAuthError(LLMError):
    code = "llm_auth"
    http_status = 502


class LLMModelNotFoundError(LLMError):
    code = "llm_model_not_found"
    http_status = 502


class LLMRateLimitError(LLMError):
    code = "llm_rate_limited"
    http_status = 429
    retryable = True

    def __init__(self, message: str, *, retry_after_s: float | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.retry_after_s = retry_after_s


class LLMTimeoutError(LLMError):
    code = "llm_timeout"
    http_status = 504
    retryable = True


class LLMProviderError(LLMError):
    """5xx / overloaded / network failures from the provider."""

    code = "llm_provider_error"
    http_status = 502
    retryable = True


class LLMBadRequestError(LLMError):
    """A 4xx the provider rejected for a reason other than auth/model/rate-limit."""

    code = "llm_bad_request"
    http_status = 502


class LLMToolCallRejected(LLMBadRequestError):
    """The provider validated the model's tool call against our schema and rejected it (Groq
    does this server-side). Retried once with the reason fed back to the model."""

    code = "llm_tool_call_rejected"


class LLMOutputError(LLMError):
    """The model's output failed schema validation twice (initial + one repair attempt)."""

    code = "llm_invalid_output"
    http_status = 502


class LLMRefusalError(LLMError):
    code = "llm_refusal"
    http_status = 422


class SpendCapExceededError(LLMError):
    code = "spend_cap_exceeded"
    http_status = 402


class BudgetExceededError(LLMError):
    """Per-run token/cost budget exhausted (agent runs)."""

    code = "budget_exceeded"
    http_status = 402


def model_not_found(provider: str, model: str, env_var: str = "LLM_MODEL") -> LLMModelNotFoundError:
    return LLMModelNotFoundError(
        f"{provider} does not recognise the model '{model}'.",
        provider=provider,
        model=model,
        hint=(
            f"Check the model ID in .env ({env_var}) against {provider}'s current model list. "
            "Retired models are not replaced automatically."
        ),
    )
