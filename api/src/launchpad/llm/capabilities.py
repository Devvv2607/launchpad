"""Per-model request quirks, in one place (so adapters stay generic).

Matched by provider + model-ID prefix (longest prefix wins). Unknown models get the
provider default, which is the most conservative choice that still works.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StructuredMode = Literal["native", "strict", "json_schema", "json_object"]


@dataclass(frozen=True)
class ModelCaps:
    # native: provider-specific schema field (Gemini responseJsonSchema, Anthropic output_config)
    # strict: OpenAI-style response_format json_schema + strict=true (constrained decoding)
    # json_schema: response_format json_schema, best effort
    # json_object: JSON mode + schema in the prompt; Pydantic does the enforcing
    structured: StructuredMode
    temperature: bool = True  # many reasoning models reject sampling params with a 400
    max_tokens_field: str = "max_tokens"


_DEFAULTS: dict[str, ModelCaps] = {
    "gemini": ModelCaps("native"),
    "groq": ModelCaps("json_object", max_tokens_field="max_completion_tokens"),
    "openai": ModelCaps("strict", temperature=False, max_tokens_field="max_completion_tokens"),
    "anthropic": ModelCaps("native", temperature=False),
}

_OVERRIDES: dict[tuple[str, str], ModelCaps] = {
    # Groq: constrained decoding only on these families (console.groq.com/docs/structured-outputs).
    ("groq", "openai/gpt-oss-"): ModelCaps("strict", max_tokens_field="max_completion_tokens"),
    ("groq", "qwen/qwen3"): ModelCaps("strict", max_tokens_field="max_completion_tokens"),
    # Anthropic: Haiku 4.5 still accepts temperature; Opus 5.5 / Sonnet 5.5 / Fable reject it.
    ("anthropic", "claude-haiku-4-5"): ModelCaps("native", temperature=True),
}


def caps_for(provider: str, model: str) -> ModelCaps:
    matches = [
        (prefix, caps)
        for (prov, prefix), caps in _OVERRIDES.items()
        if prov == provider and model.startswith(prefix)
    ]
    if matches:
        return max(matches, key=lambda m: len(m[0]))[1]
    return _DEFAULTS[provider]
