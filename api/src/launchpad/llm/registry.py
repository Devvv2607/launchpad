"""Provider clients + purpose routing.

Routing never silently falls back to a different provider: if the chosen provider has no
key or no model configured, the call fails with `LLMNotConfiguredError` and a fix hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from launchpad.config import LLMProvider, Settings, get_settings
from launchpad.llm.base import LLMClient
from launchpad.llm.errors import LLMNotConfiguredError
from launchpad.llm.types import Purpose

_KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

_clients: dict[str, LLMClient] = {}


def _api_key(s: Settings, provider: str) -> str | None:
    secret = getattr(s, f"{provider}_api_key", None)
    value = secret.get_secret_value() if secret is not None else ""
    return value or None


def configured_providers(s: Settings | None = None) -> list[str]:
    s = s or get_settings()
    return [p for p in _KEY_ENV if _api_key(s, p)]


def get_client(provider: str) -> LLMClient:
    if provider in _clients:
        return _clients[provider]
    s = get_settings()
    key = _api_key(s, provider)
    if not key:
        raise LLMNotConfiguredError(
            f"No API key configured for {provider}.",
            provider=provider,
            hint=f"Set {_KEY_ENV[provider]} in .env and restart the API.",
        )
    kw: dict[str, Any] = {"max_retries": s.llm_max_retries}
    client: LLMClient
    if provider == "gemini":
        from launchpad.llm.gemini import GeminiClient

        client = GeminiClient(key, **kw)
    elif provider == "groq":
        from launchpad.llm.openai_compat import GroqClient

        client = GroqClient(key, **kw)
    elif provider == "openai":
        from launchpad.llm.openai_compat import OpenAIClient

        client = OpenAIClient(key, **kw)
    elif provider == "anthropic":
        from launchpad.llm.anthropic_client import AnthropicClient

        client = AnthropicClient(key, **kw)
    else:  # pragma: no cover - guarded by the Literal type
        raise LLMNotConfiguredError(f"Unknown provider '{provider}'.")
    _clients[provider] = client
    return client


async def close_clients() -> None:
    for client in _clients.values():
        await client.aclose()
    _clients.clear()


class PurposeRoute(BaseModel):
    provider: LLMProvider
    model: str = Field(min_length=1, max_length=120)


class AISettings(BaseModel):
    """Stored on Workspace.ai_settings. Everything optional: env defaults apply."""

    routes: dict[Purpose, PurposeRoute] = Field(default_factory=dict)
    daily_spend_cap_usd: float | None = Field(default=None, ge=0, le=1000)


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    source: str  # "workspace" | "env"


def resolve(purpose: Purpose, ai: AISettings | None = None, s: Settings | None = None) -> Route:
    s = s or get_settings()
    override = ai.routes.get(purpose) if ai else None
    if override is not None:
        if not _api_key(s, override.provider):
            raise LLMNotConfiguredError(
                f"This workspace routes '{purpose}' to {override.provider}, which has no API key.",
                provider=override.provider,
                hint=f"Set {_KEY_ENV[override.provider]} in .env or edit the route in Settings.",
            )
        return Route(override.provider, override.model, "workspace")

    provider: str | None
    if purpose == Purpose.EMBEDDING:
        provider, model, var = (
            s.embedding_provider,
            s.embedding_model,
            "EMBEDDING_PROVIDER / EMBEDDING_MODEL",
        )
    else:
        provider = s.llm_provider
        fast = purpose == Purpose.CRITIQUE
        model = (s.llm_fast_model or s.llm_model) if fast else s.llm_model
        var = "LLM_PROVIDER / LLM_MODEL" + (" / LLM_FAST_MODEL" if fast else "")
    if not provider or not model:
        raise LLMNotConfiguredError(
            f"No model configured for '{purpose}'.",
            hint=f"Set {var} in .env (see .env.example for verified model IDs).",
        )
    return Route(provider, model, "env")
