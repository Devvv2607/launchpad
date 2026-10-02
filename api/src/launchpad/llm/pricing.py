"""Price table (USD per 1M tokens) used to *estimate* cost.

Every entry records where the number came from and when it was checked. Prices from
third-party aggregators are marked `official=False`. Models not listed have unknown cost:
we report `cost_usd=None` rather than guessing — and the UI shows "unknown".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from launchpad.llm.types import Usage


@dataclass(frozen=True)
class Price:
    input_per_m: Decimal
    output_per_m: Decimal
    source: str
    checked_on: date
    official: bool = True
    valid_until: date | None = None  # e.g. promotional pricing


_GEMINI_DOC = "https://ai.google.dev/gemini-api/docs/pricing"
_GROQ_3P = "https://eesel.ai/blog/groq-pricing (third-party; groq.com/pricing renders client-side)"
_ANTHROPIC_DOC = "Anthropic models table (claude-api skill, cached 2026-09-25)"
_D = Decimal
_CHECKED = date(2026, 10, 2)

PRICES: dict[tuple[str, str], Price] = {
    # Gemini — paid standard tier, text. 3.6-3.8 Flash are promotional until 2026-12-31.
    ("gemini", "gemini-3.8-flash"): Price(_D("0.75"), _D("3.75"), _GEMINI_DOC, _CHECKED, valid_until=date(2026, 12, 31)),
    ("gemini", "gemini-3.7-flash"): Price(_D("0.75"), _D("3.75"), _GEMINI_DOC, _CHECKED, valid_until=date(2026, 12, 31)),
    ("gemini", "gemini-3.6-flash"): Price(_D("0.75"), _D("3.75"), _GEMINI_DOC, _CHECKED, valid_until=date(2026, 12, 31)),
    ("gemini", "gemini-3.5-flash"): Price(_D("1.50"), _D("9.00"), _GEMINI_DOC, _CHECKED),
    ("gemini", "gemini-3.5-flash-lite"): Price(_D("0.30"), _D("2.50"), _GEMINI_DOC, _CHECKED),
    ("gemini", "gemini-3.1-flash-lite"): Price(_D("0.25"), _D("1.50"), _GEMINI_DOC, _CHECKED),
    ("gemini", "gemini-embedding-001"): Price(_D("0.15"), _D("0"), "web search of published rate", _CHECKED, official=False),
    # Groq
    ("groq", "llama-3.1-8b-instant"): Price(_D("0.05"), _D("0.08"), _GROQ_3P, _CHECKED, official=False),
    ("groq", "llama-3.3-70b-versatile"): Price(_D("0.59"), _D("0.79"), _GROQ_3P, _CHECKED, official=False),
    ("groq", "openai/gpt-oss-20b"): Price(_D("0.075"), _D("0.30"), _GROQ_3P, _CHECKED, official=False),
    ("groq", "openai/gpt-oss-120b"): Price(_D("0.15"), _D("0.60"), _GROQ_3P, _CHECKED, official=False),
    # Anthropic
    ("anthropic", "claude-opus-5-5"): Price(_D("4.00"), _D("20.00"), _ANTHROPIC_DOC, _CHECKED),
    ("anthropic", "claude-sonnet-5-5"): Price(_D("2.00"), _D("10.00"), _ANTHROPIC_DOC, _CHECKED),
    ("anthropic", "claude-haiku-4-5"): Price(_D("1.00"), _D("5.00"), _ANTHROPIC_DOC, _CHECKED),
}  # fmt: skip


def price_for(provider: str, model: str) -> Price | None:
    return PRICES.get((provider, model))


def estimate_cost(provider: str, model: str, usage: Usage) -> Decimal | None:
    price = price_for(provider, model)
    if price is None:
        return None
    cost = (
        Decimal(usage.input_tokens) * price.input_per_m
        + Decimal(usage.output_tokens) * price.output_per_m
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))
